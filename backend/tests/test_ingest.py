"""Tests for the M2 ingestion pipeline.

These exercise :func:`backend.app.ingest.ingest_document` against the SAVEPOINT-isolated
session fixture, so each test runs against the migrated DB but leaves no rows behind.
The CLI / `make seed` end-to-end path is covered by the CI workflow's `make seed` step
running against the empty Postgres service container.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.embeddings import FakeEmbedder
from backend.app.ingest import canonical_hash, ingest_document
from backend.app.models import SCHEMA_EMBEDDING_DIM
from backend.app.repositories import chunks as chunks_repo
from backend.app.repositories import documents as documents_repo

# A small text that produces multiple chunks under the chunker's default settings.
SAMPLE_TEXT = "Sentinel synthetic ingestion test. " * 200

# Tighter chunking config keeps the test fast and produces multiple chunks against the
# short SAMPLE_TEXT so we can verify chunk-level inserts without burning tokens.
TEST_SETTINGS = Settings(
    embeddings_provider="fake",
    chunk_size_tokens=64,
    chunk_overlap_tokens=8,
)


def test_canonical_hash_is_stable_and_collision_resistant() -> None:
    h1 = canonical_hash("alpha")
    h2 = canonical_hash("alpha")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex
    assert canonical_hash("alpha") != canonical_hash("alpha ")  # no whitespace normalization


def test_ingest_document_creates_document_and_chunks_with_embeddings(session: Session) -> None:
    embedder = FakeEmbedder()
    result = ingest_document(
        session,
        text=SAMPLE_TEXT,
        source="synthetic://doc-1",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    assert result.status == "ingested"
    assert result.chunk_count > 1
    assert result.hash == canonical_hash(SAMPLE_TEXT)

    # Document persisted.
    doc = documents_repo.get(session, result.document_id)
    assert doc is not None
    assert doc.hash == result.hash
    assert doc.source == "synthetic://doc-1"

    # All chunks persisted with embeddings of the schema dimension.
    persisted = chunks_repo.list_for_document(session, result.document_id)
    assert len(persisted) == result.chunk_count
    assert [c.ord for c in persisted] == list(range(result.chunk_count))
    for chunk in persisted:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == SCHEMA_EMBEDDING_DIM
        assert chunk.token_count > 0


def test_re_ingesting_same_content_is_a_no_op(session: Session) -> None:
    embedder = FakeEmbedder()
    first = ingest_document(
        session,
        text=SAMPLE_TEXT,
        source="synthetic://doc-2",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    assert first.status == "ingested"
    initial_chunk_count = len(chunks_repo.list_for_document(session, first.document_id))
    assert initial_chunk_count == first.chunk_count

    # Same text (hashed identically) — even from a different source path — must be a no-op.
    second = ingest_document(
        session,
        text=SAMPLE_TEXT,
        source="synthetic://different-path",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    assert second.status == "skipped"
    assert second.document_id == first.document_id
    assert second.chunk_count == 0

    # Chunk row count is unchanged.
    after = chunks_repo.list_for_document(session, first.document_id)
    assert len(after) == initial_chunk_count


def test_ingesting_different_content_creates_separate_documents(session: Session) -> None:
    embedder = FakeEmbedder()
    a = ingest_document(
        session,
        text="document A " * 100,
        source="synthetic://A",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    b = ingest_document(
        session,
        text="document B " * 100,
        source="synthetic://B",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    assert a.status == "ingested"
    assert b.status == "ingested"
    assert a.hash != b.hash
    assert a.document_id != b.document_id


def test_ingest_empty_document_creates_doc_with_no_chunks(session: Session) -> None:
    """An empty document is still a real document — recorded once, no chunks."""
    embedder = FakeEmbedder()
    result = ingest_document(
        session,
        text="",
        source="synthetic://empty",
        embedder=embedder,
        settings=TEST_SETTINGS,
    )
    assert result.status == "ingested"
    assert result.chunk_count == 0
    assert chunks_repo.list_for_document(session, result.document_id) == []
