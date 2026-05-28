"""Persistence helpers, one module per aggregate.

Each function takes an active :class:`sqlalchemy.orm.Session` and performs a single
unit of work; transaction boundaries are owned by the caller (typically the FastAPI
dependency in :mod:`backend.app.db`).

The :mod:`backend.app.repositories.audit_events` module is intentionally append-only:
it exposes ``append`` and read helpers, and *no* update or delete path. That invariant
is verified by an introspection test in ``backend/tests``.
"""
