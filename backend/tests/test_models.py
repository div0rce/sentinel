"""Round-trip and constraint tests for the M1 SQLAlchemy models."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import (
    AuditEvent,
    Chunk,
    Document,
    Extraction,
    WorkflowItem,
    WorkflowStatus,
)


def _make_document(session: Session, *, hash: str = "h" + "0" * 63) -> Document:
    doc = Document(hash=hash, source="synthetic://test", title="Test Doc")
    session.add(doc)
    session.flush()
    return doc


def test_document_round_trip(session: Session) -> None:
    doc = _make_document(session)
    assert doc.id is not None
    assert doc.created_at is not None
    assert doc.updated_at is not None

    fetched = session.get(Document, doc.id)
    assert fetched is not None
    assert fetched.hash == doc.hash
    assert fetched.source == "synthetic://test"


def test_document_hash_is_unique(session: Session) -> None:
    _make_document(session, hash="h" + "1" * 63)
    session.flush()
    duplicate = Document(hash="h" + "1" * 63, source="synthetic://other")
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_chunk_requires_document_and_round_trips(session: Session) -> None:
    doc = _make_document(session, hash="h" + "2" * 63)
    chunk = Chunk(document_id=doc.id, ord=0, text="hello world", token_count=2)
    session.add(chunk)
    session.flush()
    assert chunk.id is not None
    assert chunk.embedding is None  # nullable in M1; populated in M2


def test_chunk_unique_document_ord(session: Session) -> None:
    doc = _make_document(session, hash="h" + "3" * 63)
    session.add(Chunk(document_id=doc.id, ord=0, text="a", token_count=1))
    session.flush()
    session.add(Chunk(document_id=doc.id, ord=0, text="b", token_count=1))
    with pytest.raises(IntegrityError):
        session.flush()


def test_chunk_cascade_delete_with_document(session: Session) -> None:
    doc = _make_document(session, hash="h" + "4" * 63)
    session.add_all(
        [
            Chunk(document_id=doc.id, ord=0, text="a", token_count=1),
            Chunk(document_id=doc.id, ord=1, text="b", token_count=1),
        ]
    )
    session.flush()
    session.delete(doc)
    session.flush()
    assert session.query(Chunk).filter_by(document_id=doc.id).count() == 0


def test_extraction_payload_jsonb_round_trip(session: Session) -> None:
    doc = _make_document(session, hash="h" + "5" * 63)
    payload = {"name": "Acme", "quantities": [1, 2, 3], "nested": {"k": "v"}}
    confidence = {"name": 0.95, "quantities": 0.7}
    citations = {"name": [101], "quantities": [101, 102]}
    extraction = Extraction(
        document_id=doc.id,
        schema_name="invoice",
        payload=payload,
        field_confidence=confidence,
        field_citations=citations,
        model_name="claude-test",
    )
    session.add(extraction)
    session.flush()

    fetched = session.get(Extraction, extraction.id)
    assert fetched is not None
    assert fetched.payload == payload
    assert fetched.field_confidence == confidence
    assert fetched.field_citations == citations


def test_workflow_item_status_enum_and_idempotency(session: Session) -> None:
    doc = _make_document(session, hash="h" + "6" * 63)
    extraction = Extraction(
        document_id=doc.id, schema_name="x", payload={}, field_confidence={}, field_citations={}
    )
    session.add(extraction)
    session.flush()

    item = WorkflowItem(
        extraction_id=extraction.id,
        status=WorkflowStatus.NEEDS_REVIEW,
        idempotency_key="key-1",
    )
    session.add(item)
    session.flush()
    assert item.status is WorkflowStatus.NEEDS_REVIEW

    duplicate = WorkflowItem(
        extraction_id=extraction.id,
        status=WorkflowStatus.AUTO_APPROVED,
        idempotency_key="key-1",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_audit_event_jsonb_before_after_round_trip(session: Session) -> None:
    event = AuditEvent(
        actor="user:alice",
        action="review.approved",
        target_type="workflow_item",
        target_id=42,
        before={"status": "needs_review"},
        after={"status": "auto_approved"},
        request_id="req-abc-123",
    )
    session.add(event)
    session.flush()

    fetched = session.get(AuditEvent, event.id)
    assert fetched is not None
    assert fetched.before == {"status": "needs_review"}
    assert fetched.after == {"status": "auto_approved"}
    assert fetched.ts is not None
