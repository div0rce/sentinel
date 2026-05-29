"""Tests for the M4 extraction orchestrator.

These exercise :func:`backend.app.extract.extract_document` against the
SAVEPOINT-isolated session fixture. All tests use :class:`FakeLLM` so no live API
calls happen; the LLM's "output" is whatever string we hand it.

Coverage matrix:

* valid extraction → persisted with payload, per-field confidence, per-field citations
* parse_error → non-JSON output
* parse_error → JSON but not an object (array)
* schema_invalid → missing required field
* schema_invalid → confidence out of [0, 1]
* schema_invalid → extra (forbidden) keys
* invalid_citation → ``source_chunk_id`` not in supplied chunks
* document_not_found → unknown document id
* no_chunks → document with no chunks
* unknown_schema → unregistered schema name
* failures do NOT persist any extraction row
* markdown fences around JSON are stripped
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.extract import extract_document
from backend.app.extraction_schemas import InvoicePayload
from backend.app.llm import FakeLLM
from backend.app.models import Chunk, Document
from backend.app.repositories import extractions as extractions_repo

TEST_SETTINGS = Settings(llm_provider="fake", embeddings_provider="fake")


# --- helpers --------------------------------------------------------------------------


def _seed_document_with_chunks(
    session: Session, *, hash_suffix: str, texts: list[str]
) -> tuple[Document, list[Chunk]]:
    doc = Document(hash="x" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}")
    session.add(doc)
    session.flush()
    chunks: list[Chunk] = []
    for i, text in enumerate(texts):
        chunk = Chunk(document_id=doc.id, ord=i, text=text, token_count=len(text.split()))
        session.add(chunk)
        chunks.append(chunk)
    session.flush()
    return doc, chunks


def _valid_invoice_json(*, chunk_id: int) -> str:
    return json.dumps(
        {
            "invoice_number": {
                "value": "INV-2026-X",
                "confidence": 0.93,
                "source_chunk_id": chunk_id,
            },
            "vendor": {
                "value": "Acme Synthetic Co.",
                "confidence": 0.91,
                "source_chunk_id": chunk_id,
            },
            "issue_date": {"value": "2026-01-22", "confidence": 0.88, "source_chunk_id": chunk_id},
            "total_due": {"value": 1234.56, "confidence": 0.85, "source_chunk_id": chunk_id},
        }
    )


# --- happy path -----------------------------------------------------------------------


def test_extract_document_persists_validated_extraction(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(
        session,
        hash_suffix="ok",
        texts=["Invoice INV-2026-X from Acme Synthetic Co. dated 2026-01-22, total $1234.56."],
    )
    cid = chunks[0].id
    llm = FakeLLM(response=_valid_invoice_json(chunk_id=cid))

    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )

    assert result.status == "ok"
    assert result.reason is None
    assert result.extraction_id is not None
    assert result.schema_name == "invoice"
    assert result.payload == {
        "invoice_number": "INV-2026-X",
        "vendor": "Acme Synthetic Co.",
        "issue_date": "2026-01-22",
        "total_due": 1234.56,
    }
    assert result.field_confidence == {
        "invoice_number": 0.93,
        "vendor": 0.91,
        "issue_date": 0.88,
        "total_due": 0.85,
    }
    # Every field cites the only chunk we supplied.
    assert all(cs == [cid] for cs in result.field_citations.values())

    # Round-trip from the repo confirms persistence.
    fetched = extractions_repo.get(session, result.extraction_id)
    assert fetched is not None
    assert fetched.document_id == doc.id
    assert fetched.schema_name == "invoice"
    assert fetched.payload == result.payload
    assert fetched.field_confidence == result.field_confidence
    assert fetched.field_citations == result.field_citations
    assert fetched.model_name == "fake-llm"


def test_extract_document_strips_markdown_fences(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="fence", texts=["irrelevant"])
    fenced = "```json\n" + _valid_invoice_json(chunk_id=chunks[0].id) + "\n```"
    llm = FakeLLM(response=fenced)
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "ok", result.reason


# --- failure modes --------------------------------------------------------------------


def test_extract_document_parse_error_on_non_json(session: Session) -> None:
    doc, _ = _seed_document_with_chunks(session, hash_suffix="np", texts=["x"])
    llm = FakeLLM(response="this is not JSON at all, just prose.")
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "parse_error"
    assert result.extraction_id is None


def test_extract_document_parse_error_on_json_but_not_object(session: Session) -> None:
    doc, _ = _seed_document_with_chunks(session, hash_suffix="arr", texts=["x"])
    llm = FakeLLM(response='[{"value": "x", "confidence": 0.5, "source_chunk_id": 1}]')
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "parse_error"


def test_extract_document_schema_invalid_missing_field(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="mf", texts=["x"])
    cid = chunks[0].id
    # Drop one required field.
    payload = {
        "invoice_number": {"value": "I1", "confidence": 0.9, "source_chunk_id": cid},
        "vendor": {"value": "V", "confidence": 0.9, "source_chunk_id": cid},
        "issue_date": {"value": "2026-01-01", "confidence": 0.9, "source_chunk_id": cid},
        # total_due missing
    }
    llm = FakeLLM(response=json.dumps(payload))
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "schema_invalid"


def test_extract_document_schema_invalid_confidence_out_of_range(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="cf", texts=["x"])
    cid = chunks[0].id
    payload = json.loads(_valid_invoice_json(chunk_id=cid))
    payload["invoice_number"]["confidence"] = 1.7
    llm = FakeLLM(response=json.dumps(payload))
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "schema_invalid"


def test_extract_document_schema_invalid_extra_keys(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="ek", texts=["x"])
    cid = chunks[0].id
    payload = json.loads(_valid_invoice_json(chunk_id=cid))
    payload["unknown_field"] = {"value": "boom", "confidence": 0.5, "source_chunk_id": cid}
    llm = FakeLLM(response=json.dumps(payload))
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "schema_invalid"


def test_extract_document_schema_invalid_issue_date_shape(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="dt", texts=["x"])
    cid = chunks[0].id
    payload = json.loads(_valid_invoice_json(chunk_id=cid))
    payload["issue_date"]["value"] = "Jan 22, 2026"
    before_count = len(extractions_repo.list_for_document(session, doc.id))

    llm = FakeLLM(response=json.dumps(payload))
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )

    assert result.status == "failed"
    assert result.reason == "schema_invalid"
    after_count = len(extractions_repo.list_for_document(session, doc.id))
    assert after_count == before_count


def test_extract_document_invalid_citation_when_chunk_not_in_context(session: Session) -> None:
    doc, chunks = _seed_document_with_chunks(session, hash_suffix="bg", texts=["x"])
    cid = chunks[0].id
    payload = json.loads(_valid_invoice_json(chunk_id=cid))
    # Replace one citation with a chunk id that does not exist in the supplied set.
    payload["vendor"]["source_chunk_id"] = 9_999_999
    llm = FakeLLM(response=json.dumps(payload))
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "invalid_citation"
    assert result.detail is not None and "9999999" in result.detail


def test_extract_document_returns_document_not_found(session: Session) -> None:
    llm = FakeLLM(response="never used")
    result = extract_document(
        session,
        document_id=99_999_999,
        schema_name="invoice",
        llm=llm,
        settings=TEST_SETTINGS,
    )
    assert result.status == "failed"
    assert result.reason == "document_not_found"


def test_extract_document_returns_no_chunks_for_empty_doc(session: Session) -> None:
    doc = Document(hash="x" + "empty".ljust(63, "0"), source="test://empty")
    session.add(doc)
    session.flush()
    llm = FakeLLM(response="never used")
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == "no_chunks"


def test_extract_document_unknown_schema(session: Session) -> None:
    doc, _ = _seed_document_with_chunks(session, hash_suffix="us", texts=["x"])
    llm = FakeLLM(response="never used")
    result = extract_document(
        session,
        document_id=doc.id,
        schema_name="not-a-real-schema",
        llm=llm,
        settings=TEST_SETTINGS,
    )
    assert result.status == "failed"
    assert result.reason == "unknown_schema"


# --- failures do not persist ----------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        ("not JSON", "parse_error"),
        ('{"invoice_number": "incomplete"}', "schema_invalid"),
    ],
)
def test_failed_extractions_do_not_persist(
    session: Session, response: str, expected_reason: str
) -> None:
    doc, _ = _seed_document_with_chunks(
        session, hash_suffix=f"np-{expected_reason[:4]}", texts=["x"]
    )
    before_count = len(extractions_repo.list_for_document(session, doc.id))
    llm = FakeLLM(response=response)
    result = extract_document(
        session, document_id=doc.id, schema_name="invoice", llm=llm, settings=TEST_SETTINGS
    )
    assert result.status == "failed"
    assert result.reason == expected_reason
    after_count = len(extractions_repo.list_for_document(session, doc.id))
    assert after_count == before_count


# --- sanity on the schema layer used by the orchestrator -----------------------------


def test_invoice_schema_round_trips() -> None:
    parsed = InvoicePayload.model_validate(json.loads(_valid_invoice_json(chunk_id=1)))
    assert parsed.invoice_number.value == "INV-2026-X"
    assert parsed.total_due.value == pytest.approx(1234.56)


def test_invoice_schema_rejects_non_iso_issue_date() -> None:
    payload = json.loads(_valid_invoice_json(chunk_id=1))
    payload["issue_date"]["value"] = "unknown"

    with pytest.raises(ValidationError):
        InvoicePayload.model_validate(payload)


def test_invoice_schema_json_schema_constrains_issue_date_shape() -> None:
    schema = InvoicePayload.model_json_schema()
    issue_date_ref = schema["properties"]["issue_date"]["$ref"]
    issue_date_def = schema["$defs"][issue_date_ref.removeprefix("#/$defs/")]

    assert issue_date_def["properties"]["value"]["pattern"] == r"^\d{4}-\d{2}-\d{2}$"
