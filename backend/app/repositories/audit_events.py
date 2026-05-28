"""Append-only persistence for :class:`backend.app.models.AuditEvent`.

This module is intentionally **append-only**: it exposes :func:`append` and read
helpers, and exposes *no* update or delete path. That is the M1 invariant
(``audit_events`` has no update/delete path in the repository layer) and the
foundation for the M7 invariant that current state can be replayed from this table.

An introspection test in ``backend/tests/test_audit_events_append_only.py`` enforces
the surface so the rule cannot be quietly broken later.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AuditEvent


def append(
    session: Session,
    *,
    actor: str,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Insert a new audit event and flush so its ``id`` and ``ts`` are populated.

    ``before`` and ``after`` snapshots are stored verbatim as JSONB so the M7 replay
    test can reconstruct any aggregate's state from this table alone.
    """
    event = AuditEvent(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        request_id=request_id,
    )
    session.add(event)
    session.flush()
    return event


def list_for_target(session: Session, target_type: str, target_id: int) -> list[AuditEvent]:
    """Return every event recorded against a given target, oldest first.

    Oldest-first ordering is what the M7 replay test consumes to reconstruct state.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.target_type == target_type, AuditEvent.target_id == target_id)
        .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def list_by_request_id(session: Session, request_id: str) -> list[AuditEvent]:
    """Return every event tagged with this request id, oldest first."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.request_id == request_id)
        .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def get(session: Session, event_id: int) -> AuditEvent | None:
    """Look up a single event by id (read-only)."""
    return session.get(AuditEvent, event_id)
