"""CRUD helpers for :class:`backend.app.models.Chunk`.

Vector retrieval (cosine top-k) lives in M3; this module only handles bulk insert and
per-document read paths used by the ingestion pipeline (M2).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Chunk


class ChunkInput(TypedDict, total=False):
    """Caller-supplied data for a chunk insert. ``embedding`` is optional in M1."""

    ord: int
    text: str
    token_count: int
    embedding: Sequence[float] | None


def bulk_insert(session: Session, *, document_id: int, chunks: Iterable[ChunkInput]) -> list[Chunk]:
    """Insert chunks for a document and return them with populated ids.

    Caller is responsible for ensuring ``ord`` values are unique within ``document_id`` —
    the ``uq_chunks_document_id_ord`` index will reject duplicates with an
    :class:`sqlalchemy.exc.IntegrityError`, which the ingestion pipeline can use to
    detect re-ingestion.
    """
    instances: list[Chunk] = []
    for c in chunks:
        embedding = c.get("embedding")
        instances.append(
            Chunk(
                document_id=document_id,
                ord=c["ord"],
                text=c["text"],
                token_count=c["token_count"],
                embedding=list(embedding) if embedding is not None else None,
            )
        )
    session.add_all(instances)
    session.flush()
    return instances


def list_for_document(session: Session, document_id: int) -> list[Chunk]:
    """Return chunks for a document ordered by ``ord``."""
    stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ord)
    return list(session.execute(stmt).scalars().all())


def get(session: Session, chunk_id: int) -> Chunk | None:
    return session.get(Chunk, chunk_id)
