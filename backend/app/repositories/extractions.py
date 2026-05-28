"""CRUD helpers for :class:`backend.app.models.Extraction`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Extraction


def create(
    session: Session,
    *,
    document_id: int,
    schema_name: str,
    payload: dict[str, Any],
    field_confidence: dict[str, float] | None = None,
    field_citations: dict[str, list[int]] | None = None,
    model_name: str | None = None,
) -> Extraction:
    """Insert a new :class:`Extraction` and flush so its ``id`` is populated."""
    extraction = Extraction(
        document_id=document_id,
        schema_name=schema_name,
        payload=payload,
        field_confidence=field_confidence or {},
        field_citations=field_citations or {},
        model_name=model_name,
    )
    session.add(extraction)
    session.flush()
    return extraction


def get(session: Session, extraction_id: int) -> Extraction | None:
    return session.get(Extraction, extraction_id)


def list_for_document(session: Session, document_id: int) -> list[Extraction]:
    """Return extractions for a document, newest first."""
    stmt = (
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.created_at.desc(), Extraction.id.desc())
    )
    return list(session.execute(stmt).scalars().all())
