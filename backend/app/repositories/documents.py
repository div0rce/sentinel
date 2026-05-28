"""CRUD helpers for :class:`backend.app.models.Document`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Document


def create(
    session: Session,
    *,
    hash: str,
    source: str,
    title: str | None = None,
    mime_type: str | None = None,
) -> Document:
    """Insert a new :class:`Document` and flush so its ``id`` is populated."""
    document = Document(hash=hash, source=source, title=title, mime_type=mime_type)
    session.add(document)
    session.flush()
    return document


def get(session: Session, document_id: int) -> Document | None:
    """Return the document with this id, or ``None`` if it does not exist."""
    return session.get(Document, document_id)


def get_by_hash(session: Session, content_hash: str) -> Document | None:
    """Return the document keyed by content hash (used for idempotent ingestion in M2)."""
    stmt = select(Document).where(Document.hash == content_hash)
    return session.execute(stmt).scalar_one_or_none()


def list_all(session: Session, *, limit: int = 100, offset: int = 0) -> list[Document]:
    """Return documents ordered by ``id`` ascending. Pagination is opt-in."""
    stmt = select(Document).order_by(Document.id).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())
