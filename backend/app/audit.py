"""Semantic audit emitters and state-from-replay reconstruction.

The append-only ``audit_events`` table and its repository (with no update / delete
path) live in M1. M7 layers semantic, named-action emitters on top:

* :func:`emit_extraction_created` — model produced a new structured extraction (M4).
* :func:`emit_workflow_routed` — the rule engine assigned a workflow status (M6),
  emitted only when the workflow item was actually inserted or transitioned.
* :func:`emit_review_decision` — a human approved or rejected a workflow item (M7).

Each emitter records ``before`` / ``after`` JSON snapshots so the M7
**state-from-replay** test can rebuild current state from the audit log alone.
:func:`replay_workflow_state` is that rebuild, materialised: it walks every event
recorded against a ``workflow_item`` target oldest-first and returns the final
status.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from sqlalchemy.orm import Session

from backend.app.models import (
    AuditEvent,
    Extraction,
    WorkflowItem,
    WorkflowStatus,
)
from backend.app.repositories import audit_events as audit_events_repo

# --- semantic action constants ------------------------------------------------------


class AuditAction:
    """Stable string identifiers for the catalogue of audit actions Sentinel emits.

    Strings, not an Enum, so a future migration can add new actions without
    coordinating an enum-type migration on the DB side. Test
    ``test_audit_action_catalogue_is_stable`` pins the current set.
    """

    EXTRACTION_CREATED: Final[str] = "extraction.created"
    WORKFLOW_ROUTED: Final[str] = "workflow.routed"
    REVIEW_APPROVED: Final[str] = "review.approved"
    REVIEW_REJECTED: Final[str] = "review.rejected"


# Target types used in audit_events.target_type. Strings, same reasoning.
TARGET_EXTRACTION: Final[str] = "extraction"
TARGET_WORKFLOW_ITEM: Final[str] = "workflow_item"


# --- emitters -----------------------------------------------------------------------


def emit_extraction_created(
    session: Session,
    *,
    extraction: Extraction,
    actor: str = "system:extract",
    request_id: str | None = None,
) -> AuditEvent:
    """Record that the model produced a new ``Extraction`` (M4).

    The ``after`` JSON snapshot includes the schema name, payload, per-field
    confidence, per-field citations, and the model id — enough to reconstruct the
    suggestion without joining back to the ``extractions`` row.
    """
    after: dict[str, Any] = {
        "schema_name": extraction.schema_name,
        "payload": dict(extraction.payload),
        "field_confidence": dict(extraction.field_confidence),
        "field_citations": {k: list(v) for k, v in extraction.field_citations.items()},
        "model_name": extraction.model_name,
    }
    return audit_events_repo.append(
        session,
        actor=actor,
        action=AuditAction.EXTRACTION_CREATED,
        target_type=TARGET_EXTRACTION,
        target_id=extraction.id,
        before=None,
        after=after,
        request_id=request_id,
    )


def emit_workflow_routed(
    session: Session,
    *,
    workflow_item: WorkflowItem,
    prior_status: WorkflowStatus | None,
    actor: str = "system:workflow",
    request_id: str | None = None,
) -> AuditEvent:
    """Record a workflow routing decision (M6) that actually changed state.

    Callers must check whether the routing produced a new row or a status change
    before invoking this emitter; idempotent re-routes that are no-ops should NOT
    emit. ``prior_status`` is ``None`` for inserts.
    """
    before = None if prior_status is None else {"status": prior_status.value}
    after = {
        "status": workflow_item.status.value,
        "reason": workflow_item.reason,
        "extraction_id": workflow_item.extraction_id,
    }
    return audit_events_repo.append(
        session,
        actor=actor,
        action=AuditAction.WORKFLOW_ROUTED,
        target_type=TARGET_WORKFLOW_ITEM,
        target_id=workflow_item.id,
        before=before,
        after=after,
        request_id=request_id,
    )


ReviewDecision = Literal["approved", "rejected"]


def emit_review_decision(
    session: Session,
    *,
    workflow_item: WorkflowItem,
    prior_status: WorkflowStatus,
    decision: ReviewDecision,
    actor: str,
    note: str | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Record a human approve/reject decision on a workflow item (M7).

    The ``actor`` is the human's identifier (e.g., ``user:alice``); authentication
    plumbing arrives in M8. ``decision`` selects the semantic action; ``note`` is
    optional free-text the reviewer attached, persisted in ``after``.
    """
    if decision == "approved":
        action = AuditAction.REVIEW_APPROVED
    elif decision == "rejected":
        action = AuditAction.REVIEW_REJECTED
    else:  # pragma: no cover - guarded by Literal at the call site
        raise ValueError(f"Unknown review decision: {decision!r}")

    before = {"status": prior_status.value}
    after: dict[str, Any] = {
        "status": workflow_item.status.value,
        "reason": workflow_item.reason,
    }
    if note is not None:
        after["note"] = note
    return audit_events_repo.append(
        session,
        actor=actor,
        action=action,
        target_type=TARGET_WORKFLOW_ITEM,
        target_id=workflow_item.id,
        before=before,
        after=after,
        request_id=request_id,
    )


# --- state from replay --------------------------------------------------------------


_STATUS_BY_VALUE: Final[dict[str, WorkflowStatus]] = {s.value: s for s in WorkflowStatus}


def replay_workflow_state(session: Session, *, workflow_item_id: int) -> WorkflowStatus | None:
    """Reconstruct a workflow item's current status from the audit log alone.

    Walks every :class:`AuditEvent` recorded against ``(target_type='workflow_item',
    target_id=workflow_item_id)`` oldest-first, applies the documented event
    semantics, and returns the resulting :class:`WorkflowStatus`. Returns ``None``
    if no relevant event has ever been recorded.

    This is the M7 keystone: passing this function the right inputs must produce
    the same value persisted on ``workflow_items.status``. The state-from-replay
    test pins that equality across a multi-event lifecycle.
    """
    state: WorkflowStatus | None = None
    for event in audit_events_repo.list_for_target(session, TARGET_WORKFLOW_ITEM, workflow_item_id):
        after = event.after
        if after is None:
            continue
        new_status = after.get("status")
        if not isinstance(new_status, str):
            continue
        candidate = _STATUS_BY_VALUE.get(new_status)
        if candidate is None:
            continue
        state = candidate
    return state
