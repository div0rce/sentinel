"""Database engine, session factory, and FastAPI dependency.

The engine is created lazily on first use so test fixtures can mutate the environment
(``DATABASE_URL`` etc.) before construction. The pgvector type adapter is registered
on every new connection but only after the ``vector`` extension exists, so this module
is safe to import against a fresh database that has not yet run the M1 migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _register_pgvector_adapter(dbapi_connection: Any, _connection_record: Any) -> None:
    """Connection-level event handler that registers the pgvector type adapter.

    The ``vector`` Postgres type is created by the M1 migration. Before that migration
    runs the type does not exist yet, so we probe ``pg_type`` first and skip registration
    when absent — this lets ``alembic upgrade head`` itself open a connection cleanly.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SELECT 1 FROM pg_type WHERE typname = 'vector'")
        vector_type_exists = cursor.fetchone() is not None
    finally:
        cursor.close()

    if vector_type_exists:
        # Imported lazily so importing backend.app.db never requires the C extension
        # at module-load time; useful in environments without psycopg's binary wheel.
        from pgvector.psycopg import register_vector

        register_vector(dbapi_connection)


def _build_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    event.listen(engine, "connect", _register_pgvector_adapter)
    return engine


def get_engine() -> Engine:
    """Return the process-wide :class:`Engine`, building it on first call."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide :class:`sessionmaker`, building it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a managed :class:`Session`.

    Usage::

        @router.get("/...")
        def handler(session: Session = Depends(get_session)) -> ...:
            ...
    """
    factory = get_session_factory()
    with factory() as session:
        yield session


def reset_engine_for_tests() -> None:
    """Drop the cached engine and session factory.

    Called by test fixtures that change the environment between cases. Production code
    must not call this — it exists to keep test isolation deterministic.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
