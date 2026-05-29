"""Tests for the M6 deterministic workflow engine.

Coverage maps directly onto the M6 DoD:

* **Determinism** — :func:`route` is a pure function of its inputs; identical inputs
  produce identical outputs across runs and processes; the idempotency key recipe
  depends only on the documented inputs.
* **Idempotency** — :func:`apply_routing` upserts by deterministic key; repeated
  calls produce one ``workflow_items`` row, not duplicates.
* **Replay** — :func:`replay` rebuilds the decision from stored extraction state.
* **Invariants** — ``auto_approved`` cannot coexist with low confidence; rejecting
  guardrail flags must yield ``rejected``; ``REJECTED`` cannot be promoted to
  ``AUTO_APPROVED`` through ``apply_routing`` alone (M7's audit-driven approval is
  the only legitimate path).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import Extraction, WorkflowItem, WorkflowStatus
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import extractions as extractions_repo
from backend.app.workflow import (
    ROUTING_VERSION,
    IllegalTransition,
    RoutingDecision,
    RoutingInputs,
    _check_invariants,
    apply_routing,
    compute_idempotency_key,
    replay,
    route,
    route_extraction,
)

# --- helpers ------------------------------------------------------------------------


def _make_inputs(
    *,
    extraction_id: int = 1,
    schema_name: str = "invoice",
    field_confidence: dict[str, float] | None = None,
    guardrail_flags: tuple[str, ...] = (),
    threshold: float = 0.75,
) -> RoutingInputs:
    return RoutingInputs(
        extraction_id=extraction_id,
        schema_name=schema_name,
        field_confidence=field_confidence or {"a": 0.95, "b": 0.95},
        guardrail_flags=guardrail_flags,
        confidence_review_threshold=threshold,
    )


def _seed_extraction(
    session: Session,
    *,
    hash_suffix: str,
    field_confidence: dict[str, float],
    schema_name: str = "invoice",
) -> Extraction:
    doc = documents_repo.create(
        session, hash="w" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}"
    )
    extraction = extractions_repo.create(
        session,
        document_id=doc.id,
        schema_name=schema_name,
        payload={k: f"value-{k}" for k in field_confidence},
        field_confidence=field_confidence,
        field_citations={k: [doc.id] for k in field_confidence},
    )
    return extraction


# --- determinism --------------------------------------------------------------------


def test_route_is_a_pure_function_of_inputs() -> None:
    inputs = _make_inputs(field_confidence={"a": 0.92, "b": 0.99, "c": 0.81})
    a = route(inputs)
    b = route(inputs)
    c = route(_make_inputs(field_confidence={"a": 0.92, "b": 0.99, "c": 0.81}))
    assert a == b == c


def test_route_produces_equal_decisions_for_logically_equal_inputs() -> None:
    """Order of dict insertion in field_confidence must not change the decision."""
    a = route(_make_inputs(field_confidence={"x": 0.9, "y": 0.95}))
    b = route(_make_inputs(field_confidence={"y": 0.95, "x": 0.9}))
    assert a == b


def test_idempotency_key_depends_only_on_extraction_id_schema_and_version() -> None:
    base = compute_idempotency_key(extraction_id=42, schema_name="invoice")
    assert base == compute_idempotency_key(extraction_id=42, schema_name="invoice")

    # changing extraction_id changes the key
    assert base != compute_idempotency_key(extraction_id=43, schema_name="invoice")
    # changing schema name changes the key
    assert base != compute_idempotency_key(extraction_id=42, schema_name="purchase_order")
    # changing routing version changes the key
    assert base != compute_idempotency_key(
        extraction_id=42, schema_name="invoice", routing_version="v2"
    )


def test_idempotency_key_is_independent_of_confidence_or_flags() -> None:
    """Confidence + guardrail flags can legitimately change between routing calls;
    the key must NOT include them, otherwise re-running on the same extraction
    would be miscategorised as new work."""
    a = route(_make_inputs(field_confidence={"a": 0.9, "b": 0.9}))
    b = route(_make_inputs(field_confidence={"a": 0.4, "b": 0.4}))
    c = route(_make_inputs(guardrail_flags=("invalid_citation",)))
    # statuses differ (b is needs_review, c is rejected) but the key is the same.
    assert a.status is not b.status
    assert a.status is not c.status
    assert a.idempotency_key == b.idempotency_key == c.idempotency_key


# --- rule precedence ----------------------------------------------------------------


def test_invalid_citation_flag_routes_to_rejected() -> None:
    decision = route(_make_inputs(guardrail_flags=("invalid_citation",)))
    assert decision.status is WorkflowStatus.REJECTED
    assert decision.reason == "guardrail_rejected"


def test_low_confidence_routes_to_needs_review() -> None:
    decision = route(_make_inputs(field_confidence={"a": 0.4, "b": 0.95}))
    assert decision.status is WorkflowStatus.NEEDS_REVIEW
    assert decision.reason == "low_confidence"


def test_non_rejecting_flag_routes_to_needs_review() -> None:
    # Any guardrail flag that isn't in the rejecting set still keeps the row out of
    # auto-approval and into review.
    decision = route(
        _make_inputs(
            guardrail_flags=("needs_human_review",),
            field_confidence={"a": 0.99, "b": 0.99},
        )
    )
    assert decision.status is WorkflowStatus.NEEDS_REVIEW
    assert decision.reason == "guardrail_review"


def test_clean_inputs_route_to_auto_approved() -> None:
    decision = route(_make_inputs(field_confidence={"a": 0.99, "b": 0.99}))
    assert decision.status is WorkflowStatus.AUTO_APPROVED
    assert decision.reason == "ok"
    assert decision.routing_version == ROUTING_VERSION


def test_invalid_citation_beats_low_confidence() -> None:
    """When both a rejecting flag and low confidence are present, the row must be
    rejected (rejection is terminal; review is not)."""
    decision = route(
        _make_inputs(
            field_confidence={"a": 0.10, "b": 0.10},
            guardrail_flags=("invalid_citation",),
        )
    )
    assert decision.status is WorkflowStatus.REJECTED


# --- invariants ---------------------------------------------------------------------


def test_check_invariants_rejects_auto_approved_with_low_confidence() -> None:
    inputs = _make_inputs(field_confidence={"a": 0.10})
    with pytest.raises(AssertionError, match="auto_approved with at least one field"):
        _check_invariants(inputs, WorkflowStatus.AUTO_APPROVED)


def test_check_invariants_rejects_non_rejected_with_rejecting_flag() -> None:
    inputs = _make_inputs(guardrail_flags=("invalid_citation",))
    with pytest.raises(AssertionError, match="rejecting guardrail flag"):
        _check_invariants(inputs, WorkflowStatus.NEEDS_REVIEW)


def test_route_never_returns_auto_approved_when_low_confidence() -> None:
    """User-visible invariant: route() never silently breaks the rule above."""
    for conf in [{"a": 0.5}, {"a": 0.0}, {"a": 0.74}, {"a": 0.5, "b": 0.99}]:
        decision = route(_make_inputs(field_confidence=conf))
        assert decision.status is not WorkflowStatus.AUTO_APPROVED, conf


# --- idempotency (persistence) ------------------------------------------------------


def test_apply_routing_inserts_workflow_item(session: Session) -> None:
    extraction = _seed_extraction(session, hash_suffix="ap1", field_confidence={"a": 0.9, "b": 0.9})
    decision = route(
        _make_inputs(extraction_id=extraction.id, field_confidence={"a": 0.9, "b": 0.9})
    )
    item = apply_routing(session, extraction_id=extraction.id, decision=decision)
    assert item.id is not None
    assert item.idempotency_key == decision.idempotency_key
    assert item.status is decision.status


def test_apply_routing_is_idempotent_no_duplicate_rows(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="idem", field_confidence={"a": 0.9, "b": 0.9}
    )
    decision = route(
        _make_inputs(extraction_id=extraction.id, field_confidence={"a": 0.9, "b": 0.9})
    )
    first = apply_routing(session, extraction_id=extraction.id, decision=decision)
    second = apply_routing(session, extraction_id=extraction.id, decision=decision)
    third = apply_routing(session, extraction_id=extraction.id, decision=decision)

    assert first.id == second.id == third.id

    # Confirm at the DB level there is exactly one row with this key.
    count = session.scalar(
        select(WorkflowItem.id).where(WorkflowItem.idempotency_key == decision.idempotency_key)
    )
    assert count is not None
    rows = session.execute(
        select(WorkflowItem).where(WorkflowItem.idempotency_key == decision.idempotency_key)
    ).all()
    assert len(rows) == 1


def test_apply_routing_updates_status_when_decision_changes(session: Session) -> None:
    """A re-run that produces a different status (e.g. low confidence newly
    detected) must update the existing row, not create a second one."""
    extraction = _seed_extraction(session, hash_suffix="upd", field_confidence={"a": 0.9, "b": 0.9})
    first_decision = route(
        _make_inputs(extraction_id=extraction.id, field_confidence={"a": 0.9, "b": 0.9})
    )
    first = apply_routing(session, extraction_id=extraction.id, decision=first_decision)
    assert first.status is WorkflowStatus.AUTO_APPROVED

    # Now the same extraction routes differently because of changed confidence
    # (still the same idempotency key).
    second_decision = route(
        _make_inputs(extraction_id=extraction.id, field_confidence={"a": 0.4, "b": 0.9})
    )
    second = apply_routing(session, extraction_id=extraction.id, decision=second_decision)
    assert second.id == first.id
    assert second.status is WorkflowStatus.NEEDS_REVIEW
    assert second.reason == "low_confidence"


def test_apply_routing_refuses_rejected_to_auto_approved_promotion(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="trans", field_confidence={"a": 0.9, "b": 0.9}
    )
    rejected_decision = route(
        _make_inputs(
            extraction_id=extraction.id,
            guardrail_flags=("invalid_citation",),
        )
    )
    apply_routing(session, extraction_id=extraction.id, decision=rejected_decision)

    promotion = RoutingDecision(
        status=WorkflowStatus.AUTO_APPROVED,
        reason="ok",
        idempotency_key=rejected_decision.idempotency_key,
    )
    with pytest.raises(IllegalTransition):
        apply_routing(session, extraction_id=extraction.id, decision=promotion)


def test_apply_routing_allows_rejected_to_needs_review_demotion(session: Session) -> None:
    """A demotion from REJECTED to NEEDS_REVIEW is allowed without an audit event;
    only the auto_approved promotion is gated. Documenting the actual policy."""
    extraction = _seed_extraction(
        session, hash_suffix="demot", field_confidence={"a": 0.9, "b": 0.9}
    )
    rejected = route(
        _make_inputs(extraction_id=extraction.id, guardrail_flags=("invalid_citation",))
    )
    apply_routing(session, extraction_id=extraction.id, decision=rejected)

    review = RoutingDecision(
        status=WorkflowStatus.NEEDS_REVIEW,
        reason="reclassified",
        idempotency_key=rejected.idempotency_key,
    )
    item = apply_routing(session, extraction_id=extraction.id, decision=review)
    assert item.status is WorkflowStatus.NEEDS_REVIEW


# --- replay -------------------------------------------------------------------------


def test_replay_recovers_decision_from_stored_extraction(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="rep", field_confidence={"a": 0.92, "b": 0.91}
    )
    settings = Settings(
        embeddings_provider="fake", llm_provider="fake", confidence_review_threshold=0.75
    )

    # First, route + persist via the convenience function.
    item = route_extraction(session, extraction_id=extraction.id, settings=settings)
    assert item.status is WorkflowStatus.AUTO_APPROVED

    # Replay must produce the same decision (modulo guardrail_flags, which replay
    # cannot reconstruct without M7 audit; replay assumes no flags).
    replayed = replay(session, extraction_id=extraction.id, settings=settings)
    assert replayed.status is WorkflowStatus.AUTO_APPROVED
    assert replayed.idempotency_key == item.idempotency_key
    assert replayed.routing_version == ROUTING_VERSION


def test_replay_handles_low_confidence_extraction(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="rep-lo", field_confidence={"a": 0.4, "b": 0.99}
    )
    settings = Settings(
        embeddings_provider="fake", llm_provider="fake", confidence_review_threshold=0.75
    )
    decision = replay(session, extraction_id=extraction.id, settings=settings)
    assert decision.status is WorkflowStatus.NEEDS_REVIEW
    assert decision.reason == "low_confidence"


def test_replay_raises_for_unknown_extraction(session: Session) -> None:
    with pytest.raises(KeyError):
        replay(session, extraction_id=99_999_999)


# --- route_extraction convenience ---------------------------------------------------


def test_route_extraction_persists_idempotently(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="re", field_confidence={"a": 0.92, "b": 0.91}
    )
    a = route_extraction(session, extraction_id=extraction.id)
    b = route_extraction(session, extraction_id=extraction.id)
    assert a.id == b.id  # same row

    rows = session.execute(
        select(WorkflowItem).where(WorkflowItem.extraction_id == extraction.id)
    ).all()
    assert len(rows) == 1


def test_route_extraction_propagates_guardrail_flags(session: Session) -> None:
    extraction = _seed_extraction(
        session, hash_suffix="re-flag", field_confidence={"a": 0.99, "b": 0.99}
    )
    item = route_extraction(
        session,
        extraction_id=extraction.id,
        guardrail_flags=("invalid_citation",),
    )
    assert item.status is WorkflowStatus.REJECTED
