"""CRUD helpers for :class:`backend.app.models.WorkflowItem`.

The actual *routing rules* and idempotency-key generation live in the workflow engine
(M6); this module only persists items, looks them up, and lets the caller transition
status. Audit events for transitions are emitted by the engine in M6/M7, not here, so
this module stays a thin SQL adapter.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import WorkflowItem, WorkflowStatus


def create(
    session: Session,
    *,
    extraction_id: int,
    status: WorkflowStatus,
    idempotency_key: str,
    reason: str | None = None,
) -> WorkflowItem:
    """Insert a new :class:`WorkflowItem`. Conflicts on ``idempotency_key`` raise."""
    item = WorkflowItem(
        extraction_id=extraction_id,
        status=status,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    session.add(item)
    session.flush()
    return item


def get(session: Session, item_id: int) -> WorkflowItem | None:
    return session.get(WorkflowItem, item_id)


def get_by_idempotency_key(session: Session, key: str) -> WorkflowItem | None:
    """Return the item with this idempotency key, or ``None``.

    Used by the M6 workflow engine to make routing a no-op when re-applied.
    """
    stmt = select(WorkflowItem).where(WorkflowItem.idempotency_key == key)
    return session.execute(stmt).scalar_one_or_none()


def list_by_status(
    session: Session, status: WorkflowStatus, *, limit: int = 100, offset: int = 0
) -> list[WorkflowItem]:
    """Return items with a given status, newest first."""
    stmt = (
        select(WorkflowItem)
        .where(WorkflowItem.status == status)
        .order_by(WorkflowItem.created_at.desc(), WorkflowItem.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(stmt).scalars().all())


def set_status(
    session: Session,
    item_id: int,
    *,
    status: WorkflowStatus,
    reason: str | None = None,
) -> WorkflowItem | None:
    """Transition an item's status. Returns ``None`` if the item does not exist."""
    item = session.get(WorkflowItem, item_id)
    if item is None:
        return None
    item.status = status
    if reason is not None:
        item.reason = reason
    session.flush()
    return item
