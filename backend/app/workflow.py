"""Deterministic, idempotent workflow engine.

This is the differentiator. The engine has three layers, each with sharp boundaries:

1. **Pure rule layer** — :func:`route` is a function with no I/O. It maps a
   :class:`RoutingInputs` (an extraction's payload, per-field confidence, guardrail
   flags, and thresholds) to a :class:`RoutingDecision` (status + reason +
   idempotency key). Identical inputs always produce identical outputs.

2. **Idempotency key recipe** — :func:`compute_idempotency_key` is the SHA-256 of a
   canonical string built from the extraction id, its schema name, and the
   :data:`ROUTING_VERSION`. The version constant lets a future milestone bump the
   rule set without colliding with old keys; bumping it is auditable and triggers
   re-routing.

3. **Persistence layer** — :func:`apply_routing` creates a ``workflow_items`` row
   through an atomic conflict-safe insert keyed by the deterministic idempotency key.
   Re-running with the same decision is a no-op. Transitioning a ``REJECTED`` row to
   ``AUTO_APPROVED`` through this path is refused (M7's audit-driven approval flow is
   the only legitimate route).

Invariants enforced at decision time:

* A low-confidence flag forces ``needs_review`` or ``rejected``; ``auto_approved``
  with low confidence is impossible.
* The status returned is one of the three :class:`WorkflowStatus` values.
* The reason string is non-empty.

The engine never touches the LLM, never reads chunks, and never writes anywhere
except ``workflow_items`` (in :func:`apply_routing`).  ``replay`` rebuilds a
decision from the stored extraction with no DB writes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.orm import Session

from backend.app.audit import emit_workflow_routed
from backend.app.config import Settings, get_settings
from backend.app.guardrails import requires_review
from backend.app.models import WorkflowItem, WorkflowStatus
from backend.app.repositories import extractions as extractions_repo
from backend.app.repositories import workflow_items as workflow_items_repo

# Bumping this constant is an explicit decision: it changes every idempotency key,
# so re-running routing produces new workflow_items for previously routed
# extractions. Document the bump in PROGRESS.md and leave a backward-compatible
# fallback if you need old items to keep their keys.
ROUTING_VERSION: Final[str] = "v1"


# --- inputs / outputs ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoutingInputs:
    """Everything the rule layer needs. No DB session, no IDs of moving parts.

    The fields are exactly what a replay needs to reconstruct from storage: the
    extraction's identity (``extraction_id``, ``schema_name``), its measurements
    (``field_confidence``), the guardrail signals (``guardrail_flags``), and the
    thresholds the rules consult (``confidence_review_threshold``).
    """

    extraction_id: int
    schema_name: str
    field_confidence: Mapping[str, float]
    guardrail_flags: Sequence[str] = field(default_factory=tuple)
    confidence_review_threshold: float = 0.75


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Output of :func:`route`. ``idempotency_key`` is deterministic from inputs."""

    status: WorkflowStatus
    reason: str
    idempotency_key: str
    routing_version: str = ROUTING_VERSION


@dataclass(frozen=True, slots=True)
class RoutingPersistenceResult:
    """Outcome of persisting a routing decision."""

    item: WorkflowItem
    created: bool
    changed: bool
    prior_status: WorkflowStatus | None


# --- idempotency key ---------------------------------------------------------------


def compute_idempotency_key(
    *, extraction_id: int, schema_name: str, routing_version: str = ROUTING_VERSION
) -> str:
    """SHA-256 hex digest of a canonical join of the inputs.

    The recipe is intentionally narrow so the key depends only on stable identity
    (extraction id + schema name) and the rule set version. Inputs that legitimately
    change between routing calls — confidence scores, guardrail flags — must NOT
    be in the key, otherwise re-running on the same row would be miscategorised
    as new work.
    """
    canonical = f"{extraction_id}|{schema_name}|{routing_version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- pure rule layer --------------------------------------------------------------


_REJECTING_GUARDRAILS: Final[frozenset[str]] = frozenset({"invalid_citation"})


def _decide_status(inputs: RoutingInputs) -> tuple[WorkflowStatus, str]:
    """Return ``(status, reason)`` from inputs. No I/O."""
    if any(flag in _REJECTING_GUARDRAILS for flag in inputs.guardrail_flags):
        return WorkflowStatus.REJECTED, "guardrail_rejected"

    if requires_review(inputs.field_confidence, threshold=inputs.confidence_review_threshold):
        return WorkflowStatus.NEEDS_REVIEW, "low_confidence"

    if inputs.guardrail_flags:
        # Non-rejecting guardrail signals (e.g. a "needs_review" flag) still send
        # the row to review, never to auto-approval.
        return WorkflowStatus.NEEDS_REVIEW, "guardrail_review"

    return WorkflowStatus.AUTO_APPROVED, "ok"


def _check_invariants(inputs: RoutingInputs, status: WorkflowStatus) -> None:
    """Cheap runtime asserts on the (inputs, status) pair.

    Invariant 1: low-confidence inputs cannot result in ``auto_approved``.
    Invariant 2: any ``invalid_citation`` flag must yield ``rejected``.

    Violations raise :class:`AssertionError` so the test suite (and any production
    log) catches a rule mistake loudly rather than silently shipping a bad routing.
    """
    if status is WorkflowStatus.AUTO_APPROVED and requires_review(
        inputs.field_confidence, threshold=inputs.confidence_review_threshold
    ):
        raise AssertionError(
            "invariant violated: auto_approved with at least one field below the "
            "confidence_review_threshold"
        )

    if status is not WorkflowStatus.REJECTED and any(
        flag in _REJECTING_GUARDRAILS for flag in inputs.guardrail_flags
    ):
        raise AssertionError(
            "invariant violated: a rejecting guardrail flag must produce 'rejected'"
        )


def route(inputs: RoutingInputs) -> RoutingDecision:
    """Pure routing function. ``route(x) == route(x)`` for all x."""
    status, reason = _decide_status(inputs)
    _check_invariants(inputs, status)
    return RoutingDecision(
        status=status,
        reason=reason,
        idempotency_key=compute_idempotency_key(
            extraction_id=inputs.extraction_id, schema_name=inputs.schema_name
        ),
    )


# --- persistence (idempotent upsert) ------------------------------------------------


class IllegalTransition(RuntimeError):
    """Raised when ``apply_routing`` is asked to make a transition that the engine
    refuses without an explicit human event (introduced in M7)."""


def apply_routing(
    session: Session, *, extraction_id: int, decision: RoutingDecision
) -> WorkflowItem:
    """Insert or update the ``workflow_items`` row for ``decision``.

    This compatibility wrapper preserves the M6 API. Use
    :func:`apply_routing_result` when callers need to know whether persistence
    actually created or changed state.
    """
    return apply_routing_result(session, extraction_id=extraction_id, decision=decision).item


def apply_routing_result(
    session: Session, *, extraction_id: int, decision: RoutingDecision
) -> RoutingPersistenceResult:
    """Insert or update the ``workflow_items`` row for ``decision``.

    Idempotency: the row is keyed by ``decision.idempotency_key``. If a row already
    exists with that key:

    * **Same status** → no-op; return the existing row.
    * **Different status** → update, *unless* the existing status is ``REJECTED``
      and the new status is ``AUTO_APPROVED``. That promotion requires a human
      event and is therefore refused with :class:`IllegalTransition`.

    The create path is atomic under concurrent workers: a stale miss falls through
    to ``INSERT ... ON CONFLICT DO NOTHING`` and then reuses the winning row.
    Callers must commit the session themselves; the engine flushes but never commits.
    """
    existing = workflow_items_repo.get_by_idempotency_key(session, decision.idempotency_key)

    if existing is None:
        inserted = workflow_items_repo.create_if_absent(
            session,
            extraction_id=extraction_id,
            status=decision.status,
            idempotency_key=decision.idempotency_key,
            reason=decision.reason,
        )
        if inserted is not None:
            return RoutingPersistenceResult(
                item=inserted,
                created=True,
                changed=False,
                prior_status=None,
            )
        existing = workflow_items_repo.get_by_idempotency_key(session, decision.idempotency_key)
        if existing is None:  # pragma: no cover - defensive; conflict winner should be visible
            raise RuntimeError(
                "workflow_items.idempotency_key conflict occurred but no row was found"
            )

    if existing.status is decision.status:
        return RoutingPersistenceResult(
            item=existing,
            created=False,
            changed=False,
            prior_status=existing.status,
        )

    prior_status = existing.status
    if prior_status is WorkflowStatus.REJECTED and decision.status is WorkflowStatus.AUTO_APPROVED:
        raise IllegalTransition(
            f"workflow_items.id={existing.id} is REJECTED; promotion to AUTO_APPROVED "
            "requires an explicit human event (M7), not re-routing"
        )

    updated = workflow_items_repo.transition_from_status(
        session,
        existing.id,
        expected_status=prior_status,
        target_status=decision.status,
        reason=decision.reason,
    )
    if updated is not None:
        return RoutingPersistenceResult(
            item=updated,
            created=False,
            changed=True,
            prior_status=prior_status,
        )

    session.expire(existing)
    current = workflow_items_repo.get_by_idempotency_key(session, decision.idempotency_key)
    if current is None:  # pragma: no cover - defensive; the row existed before the transition
        raise RuntimeError(f"workflow_items.id={existing.id} disappeared during apply_routing")
    if current.status is decision.status:
        return RoutingPersistenceResult(
            item=current,
            created=False,
            changed=False,
            prior_status=current.status,
        )
    if (
        current.status is WorkflowStatus.REJECTED
        and decision.status is WorkflowStatus.AUTO_APPROVED
    ):
        raise IllegalTransition(
            f"workflow_items.id={current.id} is REJECTED; promotion to AUTO_APPROVED "
            "requires an explicit human event (M7), not re-routing"
        )
    raise RuntimeError(
        f"workflow_items.id={current.id} changed from {prior_status.value} to "
        f"{current.status.value} during apply_routing"
    )


# --- replay -------------------------------------------------------------------------


def replay(
    session: Session, *, extraction_id: int, settings: Settings | None = None
) -> RoutingDecision:
    """Recompute the routing decision for ``extraction_id`` from stored inputs.

    This is the M6 replay primitive. It reads the persisted extraction (payload,
    per-field confidence, schema name) and runs :func:`route` against it. The
    function does not write to the database.

    Raises :class:`KeyError` if the extraction does not exist; that is a programming
    error in the caller.
    """
    settings = settings or get_settings()
    extraction = extractions_repo.get(session, extraction_id)
    if extraction is None:
        raise KeyError(f"extraction {extraction_id} not found")

    inputs = RoutingInputs(
        extraction_id=extraction.id,
        schema_name=extraction.schema_name,
        field_confidence=dict(extraction.field_confidence),
        guardrail_flags=(),
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    return route(inputs)


def route_extraction(
    session: Session,
    *,
    extraction_id: int,
    guardrail_flags: Sequence[str] = (),
    settings: Settings | None = None,
) -> WorkflowItem:
    """Convenience: replay-style decision from storage + idempotent persistence.

    Use this when you have an extraction id and want it routed-and-stored in one
    call; the M9 eval harness and the future review-queue worker can call this.
    """
    settings = settings or get_settings()
    extraction = extractions_repo.get(session, extraction_id)
    if extraction is None:
        raise KeyError(f"extraction {extraction_id} not found")

    inputs = RoutingInputs(
        extraction_id=extraction.id,
        schema_name=extraction.schema_name,
        field_confidence=dict(extraction.field_confidence),
        guardrail_flags=tuple(guardrail_flags),
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    decision = route(inputs)

    result = apply_routing_result(session, extraction_id=extraction_id, decision=decision)
    item = result.item

    if result.created or result.changed:
        emit_workflow_routed(session, workflow_item=item, prior_status=result.prior_status)
    return item
