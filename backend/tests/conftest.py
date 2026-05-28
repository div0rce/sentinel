"""Shared pytest fixtures.

The session fixture uses SQLAlchemy 2.0's ``join_transaction_mode="create_savepoint"``
so each test runs inside its own SAVEPOINT and is rolled back at the end — even if the
code under test calls ``session.commit()``. The schema is expected to be at head; CI
runs ``alembic upgrade head`` before pytest, and developers run ``make migrate``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from backend.app.db import get_engine, reset_engine_for_tests


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Process-wide engine bound to the configured DATABASE_URL."""
    reset_engine_for_tests()
    eng = get_engine()
    # Smoke-check the connection and the migrated schema before the first test runs.
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    reset_engine_for_tests()


@pytest.fixture(scope="session")
def _connection(engine: Engine) -> Iterator[Connection]:
    """One persistent connection shared across the test session for fast isolation."""
    with engine.connect() as conn:
        yield conn


@pytest.fixture
def session(_connection: Connection) -> Iterator[Session]:
    """A SAVEPOINT-isolated session. Mutations roll back when the test ends."""
    outer = _connection.begin()
    sess = Session(bind=_connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
