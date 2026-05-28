"""initial schema: pgvector extension and five M1 tables

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-28

Creates the ``vector`` extension first so the ``chunks.embedding`` column can be
declared as ``Vector(1536)``. The dimension here must match
``backend.app.models.EMBEDDING_DIM`` at the time this migration was authored;
changing the dimension requires a new migration that ``ALTER COLUMN`` re-types it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM: int = 1536


def upgrade() -> None:
    # 1. Enable pgvector. Idempotent so the migration is safe to re-run on a DB where
    #    a prior bootstrap (e.g., docker-compose init) already enabled it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create the workflow_status enum type explicitly. Doing this here (rather than
    #    letting SAEnum lazy-create on first use) keeps the migration's effect on the
    #    schema deterministic and reversible.
    workflow_status_enum = postgresql.ENUM(
        "auto_approved",
        "needs_review",
        "rejected",
        name="workflow_status",
        create_type=False,
    )
    workflow_status_enum.create(op.get_bind(), checkfirst=True)

    # 3. documents
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("hash", name="uq_documents_hash"),
    )

    # 4. chunks
    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("uq_chunks_document_id_ord", "chunks", ["document_id", "ord"], unique=True)

    # 5. extractions
    op.create_table(
        "extractions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("field_confidence", postgresql.JSONB(), nullable=False),
        sa.Column("field_citations", postgresql.JSONB(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extractions"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_extractions_document_id_documents",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])
    op.create_index("ix_extractions_schema_name", "extractions", ["schema_name"])

    # 6. workflow_items
    op.create_table(
        "workflow_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("extraction_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "auto_approved",
                "needs_review",
                "rejected",
                name="workflow_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_items"),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extractions.id"],
            name="fk_workflow_items_extraction_id_extractions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_items_idempotency_key"),
    )
    op.create_index("ix_workflow_items_extraction_id", "workflow_items", ["extraction_id"])

    # 7. audit_events (append-only at the application layer; no FK constraints because
    #    target_id is polymorphic across tables)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])


def downgrade() -> None:
    # Drop tables in reverse FK order.
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_index("ix_audit_events_ts", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_workflow_items_extraction_id", table_name="workflow_items")
    op.drop_table("workflow_items")

    op.drop_index("ix_extractions_schema_name", table_name="extractions")
    op.drop_index("ix_extractions_document_id", table_name="extractions")
    op.drop_table("extractions")

    op.drop_index("uq_chunks_document_id_ord", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_table("documents")

    workflow_status_enum = postgresql.ENUM(
        "auto_approved",
        "needs_review",
        "rejected",
        name="workflow_status",
        create_type=False,
    )
    workflow_status_enum.drop(op.get_bind(), checkfirst=True)

    op.execute("DROP EXTENSION IF EXISTS vector")
