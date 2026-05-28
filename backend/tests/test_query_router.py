"""Smoke tests for ``POST /query`` via :class:`fastapi.testclient.TestClient`.

These verify wiring (request validation, dependency injection, response shape) using
overridden dependencies so the router uses our SAVEPOINT-isolated session and the
FakeLLM/aligned-query-embedder.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.embeddings import EmbeddingProvider
from backend.app.llm import FakeLLM, LLMClient
from backend.app.main import app
from backend.app.models import SCHEMA_EMBEDDING_DIM, Chunk, Document
from backend.app.rag import REFUSAL_TEXT
from backend.app.routers.query import _embedder_dependency, _llm_dependency


def _crafted_vector(strength: float) -> list[float]:
    v = [0.0] * SCHEMA_EMBEDDING_DIM
    v[0] = strength
    v[1] = math.sqrt(max(0.0, 1.0 - strength * strength))
    return v


class _AlignedQueryEmbedder:
    @property
    def dim(self) -> int:
        return SCHEMA_EMBEDDING_DIM

    def embed(self, texts):  # type: ignore[no-untyped-def]
        unit = [0.0] * SCHEMA_EMBEDDING_DIM
        unit[0] = 1.0
        return [unit for _ in texts]


def _seed_corpus(session: Session) -> None:
    doc = Document(hash="q" + "router".ljust(63, "0"), source="test://router")
    session.add(doc)
    session.flush()
    for i, strength in enumerate((0.95, 0.85, 0.75)):
        session.add(
            Chunk(
                document_id=doc.id,
                ord=i,
                text=f"Synthetic body {i}.",
                token_count=5,
                embedding=_crafted_vector(strength),
            )
        )
    session.flush()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """TestClient with the route's session/embedder/llm overridden for isolation."""

    def override_session() -> Iterator[Session]:
        yield session

    def override_embedder() -> EmbeddingProvider:
        return _AlignedQueryEmbedder()

    canned_llm = FakeLLM(response="placeholder")  # individual tests reassign as needed

    def override_llm() -> LLMClient:
        return canned_llm

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[_embedder_dependency] = override_embedder
    app.dependency_overrides[_llm_dependency] = override_llm
    try:
        # Expose the FakeLLM so tests can mutate response/response_factory.
        client = TestClient(app)
        client.canned_llm = canned_llm  # type: ignore[attr-defined]
        yield client
    finally:
        app.dependency_overrides.clear()


def test_post_query_validates_empty_body(client: TestClient) -> None:
    resp = client.post("/query", json={})
    assert resp.status_code == 422


def test_post_query_validates_too_long(client: TestClient) -> None:
    resp = client.post("/query", json={"query": "x" * 5000})
    assert resp.status_code == 422


def test_post_query_happy_path_returns_answer_with_citations(
    client: TestClient, session: Session
) -> None:
    _seed_corpus(session)

    def cite_first(system: str, user: str) -> str:
        match = re.search(r"\[chunk:(\d+)\]", user)
        assert match is not None
        return f"The corpus says so [chunk:{match.group(1)}]."

    client.canned_llm.response_factory = cite_first  # type: ignore[attr-defined]

    resp = client.post("/query", json={"query": "What does the corpus say?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert "[chunk:" in body["answer"]
    assert len(body["citations"]) == 1
    cite = body["citations"][0]
    assert {"chunk_id", "document_id", "score", "text"} <= cite.keys()
    assert 0.0 <= cite["score"] <= 1.0
    assert body["reason"] is None


def test_post_query_refuses_on_empty_corpus(client: TestClient) -> None:
    # No chunks seeded in this test, so retrieval returns nothing.
    client.canned_llm.response = "should not be used"  # type: ignore[attr-defined]
    client.canned_llm.response_factory = None  # type: ignore[attr-defined]

    resp = client.post("/query", json={"query": "anything?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "no_support"
    assert body["citations"] == []


def test_post_query_refuses_when_llm_does_not_cite(client: TestClient, session: Session) -> None:
    _seed_corpus(session)
    client.canned_llm.response = "An uncited fluent answer."  # type: ignore[attr-defined]
    client.canned_llm.response_factory = None  # type: ignore[attr-defined]

    resp = client.post("/query", json={"query": "Tell me something."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "uncited"
    assert body["citations"] == []


def test_post_query_refuses_invalid_citation(client: TestClient, session: Session) -> None:
    _seed_corpus(session)

    def cite_real_and_fake(system: str, user: str) -> str:
        match = re.search(r"\[chunk:(\d+)\]", user)
        assert match is not None
        return f"Supported claim [chunk:{match.group(1)}]. Fabricated claim [chunk:99999999]."

    client.canned_llm.response_factory = cite_real_and_fake  # type: ignore[attr-defined]

    resp = client.post("/query", json={"query": "Tell me something."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "invalid_citation"
    assert body["answer"] == REFUSAL_TEXT
    assert body["citations"] == []
