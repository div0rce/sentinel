"""SQLAlchemy 2.x ORM models for Sentinel's persistent layer.

Five aggregates back the platform:

* :class:`Document` — an ingested source document (PDF, text, etc.).
* :class:`Chunk` — a retrieval-sized slice of a document, with an embedding (added in M2).
* :class:`Extraction` — a structured record extracted by the LLM, with per-field confidence and
  per-field source citations stored as JSON sidecars.
* :class:`WorkflowItem` — a routing decision attached to an extraction (auto-approved, needs
  human review, or rejected); its lifecycle is driven by the workflow engine in M6.
* :class:`AuditEvent` — an append-only event recording every model suggestion and human decision.

The repository layer (``backend/app/repositories/``) enforces append-only semantics on
``AuditEvent`` — at the SQL level the table is just a normal heap.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.app.config import get_settings

# A consistent constraint-naming convention keeps Alembic autogenerate diffs stable across
# environments and Postgres versions. See https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base. All models inherit from this."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Pin the embedding dimension at import time. Changing EMBEDDING_DIM later requires a
# migration to alter the column type — the value baked into the M1 migration is canonical.
EMBEDDING_DIM: int = get_settings().embedding_dim


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime`` for application-side defaults."""
    return datetime.now(UTC)


class WorkflowStatus(enum.StrEnum):
    """Routing outcomes assigned by the M6 workflow engine."""

    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class Document(Base):
    """A source document the platform has ingested."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extractions: Mapped[list[Extraction]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Document(id={self.id!r}, hash={self.hash[:12]!r}, source={self.source!r})"


class Chunk(Base):
    """A retrieval-sized slice of a :class:`Document` with an embedding."""

    __tablename__ = "chunks"
    __table_args__ = (
        # Ingestion is keyed by (document, ord); duplicates are a bug.
        Index("uq_chunks_document_id_ord", "document_id", "ord", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ord: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False)
    # Populated by the ingestion pipeline in M2; nullable here so the column can hold rows
    # before embeddings are computed and so tests can insert chunks without a vector.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Chunk(id={self.id!r}, document_id={self.document_id!r}, ord={self.ord!r})"


class Extraction(Base):
    """A schema-constrained structured record extracted from a :class:`Document`.

    ``payload`` holds the extracted fields. ``field_confidence`` and ``field_citations`` are
    parallel maps keyed by field name, recording the model's confidence and the supporting chunk
    id(s) per field — these are what the M5 guardrails and M6 workflow engine consume.
    """

    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    field_confidence: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False, default=dict)
    field_citations: Mapped[dict[str, list[int]]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="extractions")
    workflow_items: Mapped[list[WorkflowItem]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Extraction(id={self.id!r}, schema={self.schema_name!r})"


class WorkflowItem(Base):
    """The routing decision attached to an :class:`Extraction`.

    ``idempotency_key`` is unique so the workflow engine can safely re-run without producing
    duplicate items; the engine itself lives in M6.
    """

    __tablename__ = "workflow_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    extraction_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("extractions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        SAEnum(
            WorkflowStatus,
            name="workflow_status",
            native_enum=True,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    extraction: Mapped[Extraction] = relationship(back_populates="workflow_items")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"WorkflowItem(id={self.id!r}, extraction_id={self.extraction_id!r}, "
            f"status={self.status.value!r})"
        )


class AuditEvent(Base):
    """Append-only audit record. Every model suggestion and human decision lands here.

    The repository layer (see :mod:`backend.app.repositories.audit_events`) intentionally
    exposes only ``append`` and read methods — there is no SQL ``UPDATE`` or ``DELETE`` path,
    enforcing the M1 invariant in code. M7 verifies state can be replayed from this table.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # Lookups by target (e.g., "all events for workflow_item 42") and request correlation
        # are common enough to warrant supporting indexes from day one.
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AuditEvent(id={self.id!r}, action={self.action!r}, actor={self.actor!r})"
