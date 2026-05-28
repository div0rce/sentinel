"""Alembic environment.

Sourced by ``alembic upgrade``, ``alembic revision --autogenerate``, etc. The SQLAlchemy
URL comes from :class:`backend.app.config.Settings` so the same env (``DATABASE_URL``)
drives both the application and migrations — there is no second source of truth.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from backend.app.config import get_settings
from backend.app.db import get_engine

# Import the package so all model classes register with Base.metadata before we hand
# the metadata to Alembic for autogenerate diffs.
from backend.app.models import Base  # noqa: F401  (registers tables on import)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without an active DB connection (alembic upgrade --sql)."""
    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB using the application's configured engine."""
    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
