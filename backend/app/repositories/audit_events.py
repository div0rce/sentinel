"""Append-only persistence for :class:`backend.app.models.AuditEvent`.

This module is intentionally **append-only**: it exposes :func:`append` and read
helpers, and exposes *no* update or delete path. That is the M1 invariant
(``audit_events`` has no update/delete path in the repository layer) and the
foundation for the M7 invariant that current state can be replayed from this table.

An introspection test in ``backend/tests/test_audit_events_append_only.py`` enforces
the surface so the rule cannot be quietly broken later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AuditEvent

type JsonValue = str | int | float | bool | None | tuple[JsonValue, ...] | Mapping[str, JsonValue]
type JsonObject = Mapping[str, JsonValue]


class FrozenJsonList(tuple[JsonValue, ...]):
    """Immutable JSON list that compares equal to the original list representation."""

    def __new__(cls, items: Iterable[JsonValue]) -> FrozenJsonList:
        return super().__new__(cls, items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return tuple(self) == tuple(other)
        return super().__eq__(other)


@dataclass(frozen=True, slots=True)
class AuditEventRead:
    """Immutable, detached read representation of an audit event."""

    id: int
    ts: datetime
    actor: str
    action: str
    target_type: str | None
    target_id: int | None
    before: JsonObject | None
    after: JsonObject | None
    request_id: str | None


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


def list_for_target(session: Session, target_type: str, target_id: int) -> list[AuditEventRead]:
    """Return every event recorded against a given target, oldest first.

    Oldest-first ordering is what the M7 replay test consumes to reconstruct state.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.target_type == target_type, AuditEvent.target_id == target_id)
        .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
    )
    return [_to_read(event) for event in session.execute(stmt).scalars().all()]


def list_by_request_id(session: Session, request_id: str) -> list[AuditEventRead]:
    """Return every event tagged with this request id, oldest first."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.request_id == request_id)
        .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
    )
    return [_to_read(event) for event in session.execute(stmt).scalars().all()]


def get(session: Session, event_id: int) -> AuditEventRead | None:
    """Look up a single event by id (read-only)."""
    event = session.get(AuditEvent, event_id)
    if event is None:
        return None
    return _to_read(event)


def _to_read(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=event.id,
        ts=event.ts,
        actor=event.actor,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        before=_freeze_json_object(event.before),
        after=_freeze_json_object(event.after),
        request_id=event.request_id,
    )


def _freeze_json_object(value: dict[str, Any] | None) -> JsonObject | None:
    if value is None:
        return None
    return cast(JsonObject, _freeze_json(value))


def _freeze_json(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze_json(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return FrozenJsonList(_freeze_json(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return cast(JsonValue, value)
