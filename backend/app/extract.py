"""Schema-constrained structured extraction.

Pipeline:

1. Load the document and its chunks.
2. Look up the requested schema class from the registry.
3. Build a strict prompt: JSON schema description + chunk excerpts + extraction
   instructions.
4. Call the LLM at temperature ``settings.llm_temperature``.
5. Parse the model output (tolerates markdown fences but otherwise expects JSON).
6. Validate the JSON against the schema (Pydantic).
7. Verify every ``source_chunk_id`` references a chunk we actually supplied as
   context. Fabricated ids are a hard failure — same posture as the M3 RAG layer.
8. On success, persist via :mod:`backend.app.repositories.extractions`. On any
   failure, return a deterministic ``ExtractionResult(status="failed", reason=...)``
   and **do not persist** — half-baked extractions never land in the table.

Failure reasons (stable strings the M5 guardrails / M7 audit / M9 eval can bucket):

* ``document_not_found``
* ``no_chunks``
* ``unknown_schema``
* ``parse_error`` — output was not valid JSON.
* ``schema_invalid`` — JSON did not match the schema (missing fields, wrong types,
  out-of-range confidence, etc.).
* ``invalid_citation`` — a ``source_chunk_id`` was not in the supplied context.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from backend.app.audit import emit_extraction_created
from backend.app.config import Settings, get_settings
from backend.app.extraction_schemas import ExtractedField, get_schema
from backend.app.guardrails import (
    low_confidence_fields,
    redact_pii,
    requires_review,
)
from backend.app.llm import LLMClient
from backend.app.repositories import chunks as chunks_repo
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import extractions as extractions_repo

ExtractionStatus = Literal["ok", "failed"]
FailureReason = Literal[
    "document_not_found",
    "no_chunks",
    "unknown_schema",
    "parse_error",
    "schema_invalid",
    "invalid_citation",
]


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Outcome of :func:`extract_document`."""

    status: ExtractionStatus
    schema_name: str
    document_id: int
    extraction_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    field_confidence: dict[str, float] = field(default_factory=dict)
    field_citations: dict[str, list[int]] = field(default_factory=dict)
    requires_review: bool = False
    low_confidence_fields: list[str] = field(default_factory=list)
    reason: FailureReason | None = None
    detail: str | None = None


SYSTEM_PROMPT = (
    "You extract structured records from an internal document corpus.\n"
    "RULES:\n"
    "1. Output ONLY a single JSON object that conforms to the supplied JSON schema.\n"
    "2. Every field MUST be an object with keys 'value', 'confidence', "
    "'source_chunk_id'.\n"
    "3. 'confidence' is a number in [0, 1] reflecting your self-reported confidence.\n"
    "4. 'source_chunk_id' MUST be one of the chunk ids listed in the context "
    "(the integer N in [chunk:N]). Do not fabricate ids.\n"
    "5. Do not include prose, explanations, comments, or markdown outside the JSON."
)


# --- prompt construction --------------------------------------------------------------


def _build_user_prompt(
    *,
    schema_cls: type[BaseModel],
    schema_name: str,
    chunks: list[Any],
    redact: bool,
) -> str:
    schema_json = json.dumps(schema_cls.model_json_schema(), indent=2)
    parts: list[str] = [
        f"Schema (JSON Schema for the {schema_name!r} record):",
        schema_json,
        "",
        "Context (each chunk has an integer id):",
    ]
    for chunk in chunks:
        text = redact_pii(chunk.text).text if redact else chunk.text
        parts.append(f"[chunk:{chunk.id}] {text}")
    parts.append("")
    parts.append(
        f"Extract the {schema_name} record from the context above. Output the JSON object only."
    )
    return "\n".join(parts)


# --- output parsing -------------------------------------------------------------------

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Strip a single surrounding ```json fenced block if present, leave bare JSON
    untouched."""
    stripped = text.strip()
    match = _FENCE_PATTERN.match(stripped)
    if match is not None:
        return match.group(1).strip()
    return stripped


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse ``text`` as a JSON object. Raises :class:`ValueError` on any problem."""
    cleaned = _strip_markdown_fences(text)
    parsed = json.loads(cleaned)  # may raise json.JSONDecodeError → caught by caller
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


# --- field unwrapping (validated payload → flat dicts ready for the repo) ------------


def _unwrap_validated_payload(
    instance: BaseModel,
) -> tuple[dict[str, Any], dict[str, float], dict[str, list[int]]]:
    """Walk an ``ExtractedField[*]``-composed model and split it into the three flat
    dicts that the ``extractions`` table stores: value payload, per-field confidence,
    per-field citations."""
    payload: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    citations: dict[str, list[int]] = {}
    for name in type(instance).model_fields:
        field_value = getattr(instance, name)
        if not isinstance(field_value, ExtractedField):
            # Schemas are required to use ExtractedField on every field; surface this
            # programming error loudly rather than silently dropping data.
            raise TypeError(
                f"schema field {name!r} on {type(instance).__name__} is not an "
                "ExtractedField — every field must be wrapped"
            )
        payload[name] = field_value.value
        confidence[name] = field_value.confidence
        citations[name] = [field_value.source_chunk_id]
    return payload, confidence, citations


# --- orchestrator ---------------------------------------------------------------------


def _failure(
    *,
    schema_name: str,
    document_id: int,
    reason: FailureReason,
    detail: str | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        status="failed",
        schema_name=schema_name,
        document_id=document_id,
        reason=reason,
        detail=detail,
    )


def extract_document(
    session: Session,
    *,
    document_id: int,
    schema_name: str,
    llm: LLMClient,
    settings: Settings | None = None,
) -> ExtractionResult:
    """Extract a structured record for ``document_id`` against ``schema_name``."""
    settings = settings or get_settings()

    # 1. document + chunks
    document = documents_repo.get(session, document_id)
    if document is None:
        return _failure(
            schema_name=schema_name,
            document_id=document_id,
            reason="document_not_found",
        )
    chunks = chunks_repo.list_for_document(session, document_id)
    if not chunks:
        return _failure(schema_name=schema_name, document_id=document_id, reason="no_chunks")

    # 2. schema class
    try:
        schema_cls = get_schema(schema_name)
    except KeyError as err:
        return _failure(
            schema_name=schema_name,
            document_id=document_id,
            reason="unknown_schema",
            detail=str(err),
        )

    # 3-4. prompt + LLM call
    user_prompt = _build_user_prompt(
        schema_cls=schema_cls,
        schema_name=schema_name,
        chunks=chunks,
        redact=settings.pii_redaction_enabled,
    )
    response = llm.complete(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )

    # 5. parse JSON
    try:
        raw = _parse_json_object(response.text)
    except (json.JSONDecodeError, ValueError) as err:
        return _failure(
            schema_name=schema_name,
            document_id=document_id,
            reason="parse_error",
            detail=str(err),
        )

    # 6. validate against schema
    try:
        validated = schema_cls.model_validate(raw)
    except ValidationError as err:
        return _failure(
            schema_name=schema_name,
            document_id=document_id,
            reason="schema_invalid",
            detail=err.errors(include_url=False)[0].get("msg") if err.errors() else None,
        )

    # 7. unwrap fields and verify citations against the supplied chunk set
    payload, confidence, citations = _unwrap_validated_payload(validated)
    supplied_ids = {chunk.id for chunk in chunks}
    for field_name, cited_ids in citations.items():
        for cid in cited_ids:
            if cid not in supplied_ids:
                return _failure(
                    schema_name=schema_name,
                    document_id=document_id,
                    reason="invalid_citation",
                    detail=f"field {field_name!r} cites chunk {cid} which was not in context",
                )

    # 8. persist
    extraction = extractions_repo.create(
        session,
        document_id=document_id,
        schema_name=schema_name,
        payload=payload,
        field_confidence=confidence,
        field_citations=citations,
        model_name=response.model,
    )

    # 9. audit: every model suggestion writes exactly one event (M7).
    emit_extraction_created(session, extraction=extraction)

    return ExtractionResult(
        status="ok",
        schema_name=schema_name,
        document_id=document_id,
        extraction_id=extraction.id,
        payload=payload,
        field_confidence=confidence,
        field_citations=citations,
        requires_review=requires_review(confidence, threshold=settings.confidence_review_threshold),
        low_confidence_fields=low_confidence_fields(
            confidence, threshold=settings.confidence_review_threshold
        ),
    )
