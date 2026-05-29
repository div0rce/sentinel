"""End-to-end tests for the M5 guardrail wiring.

Covers:

* ingest stores redacted chunk text when ``pii_redaction_enabled`` (default).
* ingest stores raw chunk text when the toggle is off.
* document hash is computed on the *original* text either way (re-ingest
  idempotency holds across the toggle flip).
* rag.answer_query passes a redacted question + redacted chunks to the LLM.
* extract.extract_document passes redacted chunk context to the LLM.
* extract.extract_document sets ``requires_review`` exactly when any field is
  below the configured threshold; ``low_confidence_fields`` lists the offenders.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.embeddings import FakeEmbedder
from backend.app.extract import extract_document
from backend.app.ingest import canonical_hash, ingest_document
from backend.app.llm import FakeLLM
from backend.app.models import Chunk, Document
from backend.app.rag import answer_query
from backend.app.repositories import chunks as chunks_repo

PII_TEXT = (
    "Customer Acme Synthetic Co. Contact alice@example.org, phone 415-555-0123, SSN 999-99-9999."
)


# --- ingest pre-storage redaction -----------------------------------------------------


def test_ingest_redacts_chunk_text_before_storage(session: Session) -> None:
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=True,
        chunk_size_tokens=64,
        chunk_overlap_tokens=8,
    )
    result = ingest_document(
        session,
        text=PII_TEXT,
        source="test://pii-on",
        embedder=FakeEmbedder(),
        settings=settings,
    )
    assert result.status == "ingested"
    stored = chunks_repo.list_for_document(session, result.document_id)
    assert stored, "ingestion produced no chunks"
    combined = " ".join(c.text for c in stored)
    assert "alice@example.org" not in combined
    assert "415-555-0123" not in combined
    assert "999-99-9999" not in combined
    assert "[REDACTED:EMAIL]" in combined
    assert "[REDACTED:PHONE]" in combined
    assert "[REDACTED:SSN]" in combined


def test_ingest_keeps_raw_text_when_redaction_disabled(session: Session) -> None:
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=False,
        chunk_size_tokens=64,
        chunk_overlap_tokens=8,
    )
    result = ingest_document(
        session,
        text=PII_TEXT,
        source="test://pii-off",
        embedder=FakeEmbedder(),
        settings=settings,
    )
    assert result.status == "ingested"
    stored = chunks_repo.list_for_document(session, result.document_id)
    combined = " ".join(c.text for c in stored)
    assert "alice@example.org" in combined
    assert "[REDACTED:" not in combined


def test_ingest_hash_is_on_original_text_either_way(session: Session) -> None:
    settings_on = Settings(
        embeddings_provider="fake", llm_provider="fake", pii_redaction_enabled=True
    )
    result = ingest_document(
        session,
        text=PII_TEXT,
        source="test://hash-on",
        embedder=FakeEmbedder(),
        settings=settings_on,
    )
    # The hash must be the SHA-256 of the original (non-redacted) text. This is the
    # contract that keeps re-ingest idempotent across a toggle change.
    assert result.hash == canonical_hash(PII_TEXT)

    # Re-ingest with redaction disabled and a different source path: still skipped
    # because hash matches.
    settings_off = Settings(
        embeddings_provider="fake", llm_provider="fake", pii_redaction_enabled=False
    )
    second = ingest_document(
        session,
        text=PII_TEXT,
        source="test://hash-on-other-path",
        embedder=FakeEmbedder(),
        settings=settings_off,
    )
    assert second.status == "skipped"
    assert second.hash == result.hash


# --- rag pre-LLM redaction ------------------------------------------------------------


class _RecordingLLM(FakeLLM):
    """FakeLLM that captures the last (system, user) prompt for inspection."""

    last_user: str | None = None
    last_system: str | None = None

    def complete(self, *, system: str, user: str, max_tokens: int, temperature: float):  # type: ignore[no-untyped-def]
        self.last_system = system
        self.last_user = user
        return super().complete(
            system=system, user=user, max_tokens=max_tokens, temperature=temperature
        )


def _seed_chunk_with_raw_pii(session: Session, *, hash_suffix: str) -> Chunk:
    """Insert a chunk whose stored text has unredacted PII (simulating pre-M5 data)."""
    doc = Document(hash="g" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}")
    session.add(doc)
    session.flush()
    chunk = Chunk(
        document_id=doc.id,
        ord=0,
        text=f"Synthetic body. Email contact-{hash_suffix}@example.org for invoice.",
        token_count=12,
        embedding=[1.0] + [0.0] * 1535,
    )
    session.add(chunk)
    session.flush()
    return chunk


def test_rag_redacts_question_and_chunks_in_prompt(session: Session) -> None:
    chunk = _seed_chunk_with_raw_pii(session, hash_suffix="rag")
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=True,
        retrieval_top_k=3,
        retrieval_min_score=0.0,
    )

    rec = _RecordingLLM(response=f"Answer [chunk:{chunk.id}].")

    class _Q:
        @property
        def dim(self) -> int:
            return 1536

        def embed(self, texts):  # type: ignore[no-untyped-def]
            unit = [1.0] + [0.0] * 1535
            return [unit for _ in texts]

    answer_query(
        session,
        query="My email is sender-x@example.org. What is the invoice?",
        embedder=_Q(),
        llm=rec,
        settings=settings,
    )
    assert rec.last_user is not None
    # The question's PII is redacted in the prompt.
    assert "sender-x@example.org" not in rec.last_user
    assert "[REDACTED:EMAIL]" in rec.last_user
    # Chunk text PII is also redacted in the prompt body, even though it was stored raw.
    assert "contact-rag@example.org" not in rec.last_user


# --- extract pre-LLM redaction + confidence gating ------------------------------------


def _valid_invoice_json(*, chunk_id: int, confidences: dict[str, float]) -> str:
    return json.dumps(
        {
            "invoice_number": {
                "value": "INV-G-1",
                "confidence": confidences.get("invoice_number", 0.9),
                "source_chunk_id": chunk_id,
            },
            "vendor": {
                "value": "Acme Synthetic Co.",
                "confidence": confidences.get("vendor", 0.9),
                "source_chunk_id": chunk_id,
            },
            "issue_date": {
                "value": "2026-01-22",
                "confidence": confidences.get("issue_date", 0.9),
                "source_chunk_id": chunk_id,
            },
            "total_due": {
                "value": 100.0,
                "confidence": confidences.get("total_due", 0.9),
                "source_chunk_id": chunk_id,
            },
        }
    )


def test_extract_redacts_chunk_context_in_prompt(session: Session) -> None:
    chunk = _seed_chunk_with_raw_pii(session, hash_suffix="ex")
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=True,
        confidence_review_threshold=0.5,
    )
    rec = _RecordingLLM(response=_valid_invoice_json(chunk_id=chunk.id, confidences={}))

    extract_document(
        session,
        document_id=chunk.document_id,
        schema_name="invoice",
        llm=rec,
        settings=settings,
    )

    assert rec.last_user is not None
    assert "contact-ex@example.org" not in rec.last_user
    assert "[REDACTED:EMAIL]" in rec.last_user


def test_extract_requires_review_when_any_field_below_threshold(session: Session) -> None:
    chunk = _seed_chunk_with_raw_pii(session, hash_suffix="lo")
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=True,
        confidence_review_threshold=0.75,
    )
    # invoice_number well above threshold; vendor below.
    llm = FakeLLM(
        response=_valid_invoice_json(
            chunk_id=chunk.id,
            confidences={
                "vendor": 0.40,
                "invoice_number": 0.95,
                "issue_date": 0.95,
                "total_due": 0.95,
            },
        )
    )
    result = extract_document(
        session,
        document_id=chunk.document_id,
        schema_name="invoice",
        llm=llm,
        settings=settings,
    )
    assert result.status == "ok"
    assert result.requires_review is True
    assert result.low_confidence_fields == ["vendor"]


def test_extract_requires_review_false_when_all_above_threshold(session: Session) -> None:
    chunk = _seed_chunk_with_raw_pii(session, hash_suffix="hi")
    settings = Settings(
        embeddings_provider="fake",
        llm_provider="fake",
        pii_redaction_enabled=True,
        confidence_review_threshold=0.75,
    )
    llm = FakeLLM(
        response=_valid_invoice_json(
            chunk_id=chunk.id,
            confidences={
                "vendor": 0.95,
                "invoice_number": 0.95,
                "issue_date": 0.95,
                "total_due": 0.95,
            },
        )
    )
    result = extract_document(
        session,
        document_id=chunk.document_id,
        schema_name="invoice",
        llm=llm,
        settings=settings,
    )
    assert result.status == "ok"
    assert result.requires_review is False
    assert result.low_confidence_fields == []
