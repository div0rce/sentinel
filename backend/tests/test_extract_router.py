"""Smoke tests for ``POST /extract`` via :class:`fastapi.testclient.TestClient`."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.llm import FakeLLM, LLMClient
from backend.app.main import app
from backend.app.models import Chunk, Document, WorkflowItem, WorkflowStatus
from backend.app.routers.extract import _llm_dependency


def _seed_document(session: Session, *, hash_suffix: str, text: str) -> tuple[int, int]:
    doc = Document(hash="r" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}")
    session.add(doc)
    session.flush()
    chunk = Chunk(document_id=doc.id, ord=0, text=text, token_count=len(text.split()))
    session.add(chunk)
    session.flush()
    return doc.id, chunk.id


def _valid_invoice_json(*, chunk_id: int, total_due_confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "invoice_number": {"value": "R-1", "confidence": 0.9, "source_chunk_id": chunk_id},
            "vendor": {"value": "Acme", "confidence": 0.9, "source_chunk_id": chunk_id},
            "issue_date": {"value": "2026-01-22", "confidence": 0.9, "source_chunk_id": chunk_id},
            "total_due": {
                "value": 100.0,
                "confidence": total_due_confidence,
                "source_chunk_id": chunk_id,
            },
        }
    )


def _workflow_items_for_extraction(session: Session, extraction_id: int) -> list[WorkflowItem]:
    return list(
        session.scalars(
            select(WorkflowItem)
            .where(WorkflowItem.extraction_id == extraction_id)
            .order_by(WorkflowItem.id)
        )
    )


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """TestClient with session and llm overridden for isolation."""

    def override_session() -> Iterator[Session]:
        yield session

    canned_llm = FakeLLM(response="placeholder")

    def override_llm() -> LLMClient:
        return canned_llm

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[_llm_dependency] = override_llm
    try:
        client = TestClient(app)
        client.canned_llm = canned_llm  # type: ignore[attr-defined]
        yield client
    finally:
        app.dependency_overrides.clear()


def test_post_extract_validates_empty_body(client: TestClient) -> None:
    resp = client.post("/extract", json={})
    assert resp.status_code == 422


def test_post_extract_validates_zero_document_id(client: TestClient) -> None:
    resp = client.post("/extract", json={"document_id": 0, "schema_name": "invoice"})
    assert resp.status_code == 422


def test_post_extract_happy_path(client: TestClient, session: Session) -> None:
    doc_id, chunk_id = _seed_document(session, hash_suffix="hp", text="invoice text")
    client.canned_llm.response = _valid_invoice_json(chunk_id=chunk_id)  # type: ignore[attr-defined]

    resp = client.post("/extract", json={"document_id": doc_id, "schema_name": "invoice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["document_id"] == doc_id
    assert body["schema_name"] == "invoice"
    assert body["extraction_id"] is not None
    assert body["payload"]["invoice_number"] == "R-1"
    assert body["payload"]["total_due"] == 100.0
    assert body["field_confidence"]["invoice_number"] == pytest.approx(0.9)
    assert body["field_citations"]["invoice_number"] == [chunk_id]
    assert body["reason"] is None


def test_post_extract_routes_low_confidence_result_to_review_queue(
    client: TestClient, session: Session
) -> None:
    doc_id, chunk_id = _seed_document(session, hash_suffix="lo", text="invoice text")
    client.canned_llm.response = _valid_invoice_json(  # type: ignore[attr-defined]
        chunk_id=chunk_id,
        total_due_confidence=0.4,
    )

    resp = client.post("/extract", json={"document_id": doc_id, "schema_name": "invoice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["requires_review"] is True
    assert body["low_confidence_fields"] == ["total_due"]

    items = _workflow_items_for_extraction(session, body["extraction_id"])
    assert len(items) == 1
    assert items[0].status is WorkflowStatus.NEEDS_REVIEW

    queue = client.get("/review").json()["items"]
    assert [item["id"] for item in queue] == [items[0].id]


def test_post_extract_routes_high_confidence_result_out_of_review_queue(
    client: TestClient, session: Session
) -> None:
    doc_id, chunk_id = _seed_document(session, hash_suffix="hi", text="invoice text")
    client.canned_llm.response = _valid_invoice_json(chunk_id=chunk_id)  # type: ignore[attr-defined]

    resp = client.post("/extract", json={"document_id": doc_id, "schema_name": "invoice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["requires_review"] is False

    items = _workflow_items_for_extraction(session, body["extraction_id"])
    assert len(items) == 1
    assert items[0].status is WorkflowStatus.AUTO_APPROVED

    assert client.get("/review").json() == {"items": []}


def test_post_extract_returns_failed_on_malformed_llm_output(
    client: TestClient, session: Session
) -> None:
    doc_id, _ = _seed_document(session, hash_suffix="mf", text="invoice text")
    client.canned_llm.response = "not JSON"  # type: ignore[attr-defined]

    resp = client.post("/extract", json={"document_id": doc_id, "schema_name": "invoice"})
    assert resp.status_code == 200  # The endpoint surfaces failures as status='failed'.
    body = resp.json()
    assert body["status"] == "failed"
    assert body["reason"] == "parse_error"
    assert body["extraction_id"] is None
    assert session.scalars(select(WorkflowItem)).all() == []


def test_post_extract_returns_failed_for_unknown_document(client: TestClient) -> None:
    client.canned_llm.response = "never used"  # type: ignore[attr-defined]
    resp = client.post("/extract", json={"document_id": 99_999_999, "schema_name": "invoice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["reason"] == "document_not_found"


def test_post_extract_returns_failed_for_unknown_schema(
    client: TestClient, session: Session
) -> None:
    doc_id, _ = _seed_document(session, hash_suffix="us", text="invoice text")
    client.canned_llm.response = "never used"  # type: ignore[attr-defined]
    resp = client.post("/extract", json={"document_id": doc_id, "schema_name": "nope"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["reason"] == "unknown_schema"
