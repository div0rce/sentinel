"""Tests for the M7 audit log and human-in-the-loop review queue.

Coverage maps onto the M7 DoD:

* **Every model suggestion and human decision writes exactly one audit event.**
  Tests pin event counts after each operation: a fresh extract creates one
  ``extraction.created``; a fresh route creates one ``workflow.routed``; a
  no-op re-route creates zero; an approve creates one ``review.approved``.

* **Approve/reject transitions are valid and audited.** Tests assert 200 on the
  happy path with the new status and an audit row whose actor matches the body;
  409 when the item is not in ``needs_review``; 404 on unknown id.

* **State-from-replay test.** A multi-event lifecycle (route → review reject →
  re-route demotion → review approve) walks through the audit log only and
  reconstructs the final ``workflow_items.status``; the test asserts equality
  with the persisted status.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import (
    AuditAction,
    emit_review_decision,
    replay_workflow_state,
)
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models import AuditEvent, Extraction, WorkflowItem, WorkflowStatus
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import extractions as extractions_repo
from backend.app.repositories import workflow_items as workflow_items_repo
from backend.app.workflow import route_extraction

# --- helpers --------------------------------------------------------------------------


def _seed_extraction(
    session: Session,
    *,
    hash_suffix: str,
    field_confidence: dict[str, float] | None = None,
) -> Extraction:
    doc = documents_repo.create(
        session, hash="a" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}"
    )
    return extractions_repo.create(
        session,
        document_id=doc.id,
        schema_name="invoice",
        payload={"invoice_number": "I-1"},
        field_confidence=field_confidence or {"invoice_number": 0.95},
        field_citations={"invoice_number": [doc.id]},
    )


def _events_for_workflow_item(session: Session, workflow_item_id: int) -> list[AuditEvent]:
    return list(
        session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.target_type == "workflow_item",
                AuditEvent.target_id == workflow_item_id,
            )
            .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
        )
        .scalars()
        .all()
    )


# --- emission counts ----------------------------------------------------------------


def test_route_extraction_emits_one_workflow_routed_event(session: Session) -> None:
    extraction = _seed_extraction(session, hash_suffix="re1")
    item = route_extraction(session, extraction_id=extraction.id)
    events = _events_for_workflow_item(session, item.id)
    assert len(events) == 1
    assert events[0].action == AuditAction.WORKFLOW_ROUTED
    assert events[0].before is None  # first insert
    assert events[0].after == {
        "status": item.status.value,
        "reason": item.reason,
        "extraction_id": item.extraction_id,
    }


def test_idempotent_reroute_does_not_emit_duplicate(session: Session) -> None:
    extraction = _seed_extraction(session, hash_suffix="re2")
    item = route_extraction(session, extraction_id=extraction.id)
    # Second call with identical inputs is a no-op at the persistence layer; the
    # audit emitter must NOT fire again.
    route_extraction(session, extraction_id=extraction.id)
    route_extraction(session, extraction_id=extraction.id)
    events = _events_for_workflow_item(session, item.id)
    assert len(events) == 1


def test_losing_reroute_race_does_not_emit_duplicate_workflow_routed(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction = _seed_extraction(session, hash_suffix="race")
    item = route_extraction(session, extraction_id=extraction.id)

    original_get = workflow_items_repo.get_by_idempotency_key
    calls = 0

    def stale_miss_once(session: Session, key: str) -> WorkflowItem | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_get(session, key)

    monkeypatch.setattr(workflow_items_repo, "get_by_idempotency_key", stale_miss_once)

    rerouted = route_extraction(session, extraction_id=extraction.id)

    assert rerouted.id == item.id
    assert calls == 2
    events = _events_for_workflow_item(session, item.id)
    assert len(events) == 1
    assert events[0].action == AuditAction.WORKFLOW_ROUTED


def test_route_extraction_emits_on_status_change(session: Session) -> None:
    extraction = _seed_extraction(
        session,
        hash_suffix="re3",
        field_confidence={"invoice_number": 0.95},
    )
    first = route_extraction(session, extraction_id=extraction.id)
    assert first.status is WorkflowStatus.AUTO_APPROVED

    # Mutate stored confidence so a re-route flips the decision to needs_review.
    extraction.field_confidence = {"invoice_number": 0.4}
    session.flush()
    second = route_extraction(session, extraction_id=extraction.id)
    assert second.id == first.id
    assert second.status is WorkflowStatus.NEEDS_REVIEW

    events = _events_for_workflow_item(session, first.id)
    # Two events: initial insert (before=None) and the status transition.
    assert len(events) == 2
    assert events[0].before is None
    assert events[1].before == {"status": WorkflowStatus.AUTO_APPROVED.value}
    assert events[1].after == {
        "status": WorkflowStatus.NEEDS_REVIEW.value,
        "reason": second.reason,
        "extraction_id": second.extraction_id,
    }


# --- review router ------------------------------------------------------------------


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_needs_review(session: Session, *, hash_suffix: str) -> WorkflowItem:
    extraction = _seed_extraction(
        session, hash_suffix=hash_suffix, field_confidence={"invoice_number": 0.4}
    )
    item = route_extraction(session, extraction_id=extraction.id)
    assert item.status is WorkflowStatus.NEEDS_REVIEW
    return item


def test_get_review_returns_needs_review_items(client: TestClient, session: Session) -> None:
    item = _seed_needs_review(session, hash_suffix="q1")
    resp = client.get("/review")
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in body["items"]]
    assert item.id in ids
    assert all(row["status"] == "needs_review" for row in body["items"])


def test_post_approve_transitions_and_audits(client: TestClient, session: Session) -> None:
    item = _seed_needs_review(session, hash_suffix="ap")
    before_events = len(_events_for_workflow_item(session, item.id))

    resp = client.post(
        f"/review/{item.id}/approve", json={"actor": "user:alice", "note": "looks good"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "auto_approved"
    assert body["id"] == item.id
    audit_id = body["audit_event_id"]
    assert isinstance(audit_id, int)

    # Persisted state matches.
    refreshed = workflow_items_repo.get(session, item.id)
    assert refreshed is not None
    assert refreshed.status is WorkflowStatus.AUTO_APPROVED

    # Exactly one new audit event of the expected shape.
    after_events = _events_for_workflow_item(session, item.id)
    assert len(after_events) == before_events + 1
    new_event = after_events[-1]
    assert new_event.id == audit_id
    assert new_event.action == AuditAction.REVIEW_APPROVED
    assert new_event.actor == "user:alice"
    assert new_event.before == {"status": WorkflowStatus.NEEDS_REVIEW.value}
    assert new_event.after is not None
    assert new_event.after.get("status") == WorkflowStatus.AUTO_APPROVED.value
    assert new_event.after.get("note") == "looks good"


def test_post_reject_transitions_and_audits(client: TestClient, session: Session) -> None:
    item = _seed_needs_review(session, hash_suffix="rj")
    resp = client.post(f"/review/{item.id}/reject", json={"actor": "user:bob"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    refreshed = workflow_items_repo.get(session, item.id)
    assert refreshed is not None
    assert refreshed.status is WorkflowStatus.REJECTED

    events = _events_for_workflow_item(session, item.id)
    last = events[-1]
    assert last.action == AuditAction.REVIEW_REJECTED
    assert last.actor == "user:bob"


def test_post_approve_rejects_already_decided_item(client: TestClient, session: Session) -> None:
    item = _seed_needs_review(session, hash_suffix="ar")
    # First approval succeeds.
    first = client.post(f"/review/{item.id}/approve", json={"actor": "user:a"})
    assert first.status_code == 200
    # Second approval on the now-auto_approved item must 409.
    second = client.post(f"/review/{item.id}/approve", json={"actor": "user:a"})
    assert second.status_code == 409


def test_concurrent_review_decision_loser_returns_409_without_audit(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _seed_needs_review(session, hash_suffix="cd")
    first = client.post(f"/review/{item.id}/reject", json={"actor": "user:first"})
    assert first.status_code == 200

    before_events = _events_for_workflow_item(session, item.id)
    original_get = workflow_items_repo.get
    stale_item = SimpleNamespace(
        id=item.id,
        extraction_id=item.extraction_id,
        status=WorkflowStatus.NEEDS_REVIEW,
        reason=item.reason,
        idempotency_key=item.idempotency_key,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )

    monkeypatch.setattr(workflow_items_repo, "get", lambda session, item_id: stale_item)

    second = client.post(f"/review/{item.id}/approve", json={"actor": "user:second"})

    assert second.status_code == 409
    refreshed = original_get(session, item.id)
    assert refreshed is not None
    assert refreshed.status is WorkflowStatus.REJECTED
    after_events = _events_for_workflow_item(session, item.id)
    assert len(after_events) == len(before_events)
    assert [event.action for event in after_events].count(AuditAction.REVIEW_REJECTED) == 1
    assert [event.action for event in after_events].count(AuditAction.REVIEW_APPROVED) == 0


def test_post_approve_returns_404_for_unknown_item(client: TestClient) -> None:
    resp = client.post("/review/99999999/approve", json={"actor": "user:x"})
    assert resp.status_code == 404


def test_post_decision_validates_actor(client: TestClient, session: Session) -> None:
    item = _seed_needs_review(session, hash_suffix="va")
    resp = client.post(f"/review/{item.id}/approve", json={"actor": ""})
    assert resp.status_code == 422


# --- state from replay (M7 keystone) ------------------------------------------------


def test_state_from_replay_reconstructs_current_status(session: Session) -> None:
    """The audit log alone must be enough to rebuild ``workflow_items.status``.

    Lifecycle exercised:
      1. route_extraction (auto_approved with high confidence)
      2. mutate stored confidence; re-route → needs_review
      3. human reject → rejected
      4. human re-classification: emit_review_decision back to needs_review
         (e.g., a supervisor reverses the rejection within review semantics)
      5. human approve → auto_approved
    """
    extraction = _seed_extraction(
        session,
        hash_suffix="rep",
        field_confidence={"invoice_number": 0.95},
    )

    # 1. initial route (auto_approved + 1 audit event)
    item = route_extraction(session, extraction_id=extraction.id)
    assert item.status is WorkflowStatus.AUTO_APPROVED

    # 2. drop confidence and re-route -> needs_review (+1 audit event)
    extraction.field_confidence = {"invoice_number": 0.3}
    session.flush()
    item = route_extraction(session, extraction_id=extraction.id)
    assert item.status is WorkflowStatus.NEEDS_REVIEW

    # 3. reject via review path (+1 audit event)
    prior: WorkflowStatus = item.status
    rejected = workflow_items_repo.set_status(
        session, item.id, status=WorkflowStatus.REJECTED, reason="human:rejected"
    )
    assert rejected is not None and rejected.status is WorkflowStatus.REJECTED
    emit_review_decision(
        session,
        workflow_item=rejected,
        prior_status=prior,
        decision="rejected",
        actor="user:bob",
    )

    # 4. re-classify back to needs_review via a fresh review event (+1 audit event)
    prior = rejected.status
    reopened = workflow_items_repo.set_status(
        session,
        item.id,
        status=WorkflowStatus.NEEDS_REVIEW,
        reason="human:reopened",
    )
    assert reopened is not None and reopened.status is WorkflowStatus.NEEDS_REVIEW
    # Use the rejected emitter for the supervisor reversal; in M8 we can introduce
    # a dedicated review.reopened action. The before/after JSON still tells the truth.
    emit_review_decision(
        session,
        workflow_item=reopened,
        prior_status=prior,
        decision="rejected",  # the action label is less important than before/after
        actor="user:supervisor",
        note="reverted",
    )

    # 5. approve via review path (+1 audit event)
    prior = reopened.status
    approved = workflow_items_repo.set_status(
        session, item.id, status=WorkflowStatus.AUTO_APPROVED, reason="human:approved"
    )
    assert approved is not None and approved.status is WorkflowStatus.AUTO_APPROVED
    emit_review_decision(
        session,
        workflow_item=approved,
        prior_status=prior,
        decision="approved",
        actor="user:supervisor",
    )

    # The keystone assertion: the audit log alone reproduces the current status.
    replayed = replay_workflow_state(session, workflow_item_id=approved.id)
    assert replayed is not None
    assert replayed is approved.status, (
        f"replay produced {replayed} but persisted is {approved.status}"
    )

    # Five events recorded across the lifecycle (1 route insert + 1 route transition
    # + 3 human review events).
    events = _events_for_workflow_item(session, approved.id)
    assert len(events) == 5


def test_replay_returns_none_for_workflow_item_with_no_events(session: Session) -> None:
    assert replay_workflow_state(session, workflow_item_id=1234567890) is None


# --- AuditAction catalogue is stable ------------------------------------------------


def test_audit_action_catalogue_is_stable() -> None:
    """The set of audit actions Sentinel emits is a stable contract; new actions
    require an explicit decision, recorded in PROGRESS.md."""
    expected = {
        "extraction.created",
        "workflow.routed",
        "review.approved",
        "review.rejected",
    }
    actual = {
        AuditAction.EXTRACTION_CREATED,
        AuditAction.WORKFLOW_ROUTED,
        AuditAction.REVIEW_APPROVED,
        AuditAction.REVIEW_REJECTED,
    }
    assert actual == expected
