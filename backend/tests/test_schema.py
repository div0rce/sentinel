"""Verify the migrated schema matches what M1 set out to create.

DoD #1: ``make migrate`` applies cleanly on a fresh DB, with the pgvector extension
enabled. CI runs ``alembic upgrade head`` before pytest, so by the time we get here the
schema must be at head and these assertions reduce to introspection.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

EXPECTED_TABLES = {
    "alembic_version",
    "documents",
    "chunks",
    "extractions",
    "workflow_items",
    "audit_events",
}


def test_all_expected_tables_exist(engine: Engine) -> None:
    insp = inspect(engine)
    actual = set(insp.get_table_names(schema="public"))
    missing = EXPECTED_TABLES - actual
    assert not missing, f"missing tables: {missing}"


def test_vector_extension_is_enabled(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).fetchone()
    assert row is not None, "pgvector extension not installed"


def test_workflow_status_enum_values(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'workflow_status' "
                "ORDER BY enumsortorder"
            )
        ).fetchall()
    assert [r[0] for r in rows] == ["auto_approved", "needs_review", "rejected"]


def test_chunks_embedding_column_dim(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) "
                "FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "vector(1536)"


def test_alembic_version_is_at_head(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    assert row is not None
    assert row[0] == "0001_initial_schema"
