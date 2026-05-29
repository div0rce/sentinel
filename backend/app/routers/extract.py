"""``POST /extract`` — schema-constrained structured extraction endpoint."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.extract import ExtractionResult, extract_document
from backend.app.extraction_schemas import list_schemas
from backend.app.llm import LLMClient, get_llm

router = APIRouter(prefix="/extract", tags=["extract"])


# --- request / response schemas -------------------------------------------------------


class ExtractRequest(BaseModel):
    """Body for ``POST /extract``."""

    document_id: int = Field(..., ge=1, description="Id of an ingested document.")
    schema_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Registered extraction schema name. Currently registered: "
            f"{', '.join(sorted(list_schemas()))}."
        ),
    )


class ExtractResponse(BaseModel):
    """Result returned to the caller."""

    status: Literal["ok", "failed"]
    document_id: int
    schema_name: str
    extraction_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    field_citations: dict[str, list[int]] = Field(default_factory=dict)
    requires_review: bool = False
    low_confidence_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    detail: str | None = None


# --- dependency (kept as a separate callable so tests can override it) ---------------


def _llm_dependency() -> LLMClient:
    return get_llm()


# --- handler --------------------------------------------------------------------------


def _to_response(result: ExtractionResult) -> ExtractResponse:
    return ExtractResponse(
        status=result.status,
        document_id=result.document_id,
        schema_name=result.schema_name,
        extraction_id=result.extraction_id,
        payload=result.payload,
        field_confidence=result.field_confidence,
        field_citations=result.field_citations,
        requires_review=result.requires_review,
        low_confidence_fields=result.low_confidence_fields,
        reason=result.reason,
        detail=result.detail,
    )


@router.post("", response_model=ExtractResponse)
def post_extract(
    body: ExtractRequest,
    session: Annotated[Session, Depends(get_session)],
    llm: Annotated[LLMClient, Depends(_llm_dependency)],
) -> ExtractResponse:
    """Extract a structured record for an ingested document.

    The handler delegates all business logic to :func:`extract_document` and only
    converts the result to the API response shape. On a successful extraction the
    session is committed so the new ``extractions`` row is durable; failures issue
    no writes and so need no rollback.
    """
    result = extract_document(
        session,
        document_id=body.document_id,
        schema_name=body.schema_name,
        llm=llm,
    )
    if result.status == "ok":
        session.commit()
    return _to_response(result)
