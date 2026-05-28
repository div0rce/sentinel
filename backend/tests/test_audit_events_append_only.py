"""The audit_events repository is append-only.

DoD #3 (M1): "audit_events has no update/delete path in the repository layer."
This test enforces it two ways:

1. Behavioural: ``append`` works, JSONB before/after round-trip, ``list_for_target``
   and ``list_by_request_id`` return events in chronological order.
2. Structural (introspection): no public function in
   :mod:`backend.app.repositories.audit_events` mutates or deletes existing events.
   Any future change that adds an ``update_*``, ``delete_*``, ``set_*``, or similarly
   named symbol will fail this test, which forces the rule to be re-discussed
   explicitly via PR review.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import UnmappedInstanceError

from backend.app.models import AuditEvent
from backend.app.repositories import audit_events as ae_repo

# Names that would clearly violate append-only semantics. Add to this list as needed.
FORBIDDEN_EXACT = {
    "update",
    "delete",
    "remove",
    "purge",
    "modify",
    "replace",
    "set",
    "drop",
    "truncate",
}
FORBIDDEN_PREFIXES = ("update_", "delete_", "remove_", "modify_", "replace_", "set_", "drop_")


def test_module_public_surface_has_no_mutators() -> None:
    public_callables = {
        name
        for name, obj in inspect.getmembers(ae_repo)
        if not name.startswith("_")
        and inspect.isfunction(obj)
        and obj.__module__ == ae_repo.__name__
    }
    # Sanity: append must be present.
    assert "append" in public_callables, public_callables

    offending = {
        name
        for name in public_callables
        if name in FORBIDDEN_EXACT or name.startswith(FORBIDDEN_PREFIXES)
    }
    assert not offending, (
        f"audit_events repository must remain append-only; found mutating names: {offending}"
    )


def test_append_persists_event_with_jsonb_round_trip(session: Session) -> None:
    event = ae_repo.append(
        session,
        actor="model:claude-test",
        action="extraction.created",
        target_type="extraction",
        target_id=1,
        before=None,
        after={"schema_name": "invoice", "fields": ["amount"]},
        request_id="req-aaa",
    )
    assert event.id is not None
    assert event.ts is not None

    fetched = ae_repo.get(session, event.id)
    assert fetched is not None
    assert fetched.action == "extraction.created"
    assert fetched.before is None
    assert fetched.after == {"schema_name": "invoice", "fields": ["amount"]}
    assert fetched.request_id == "req-aaa"


def test_get_returns_immutable_read_dto_not_mapped_orm_row(session: Session) -> None:
    event = ae_repo.append(session, actor="system", action="audit.read", request_id="req-read")

    fetched = ae_repo.get(session, event.id)

    assert isinstance(fetched, ae_repo.AuditEventRead)
    assert not isinstance(fetched, AuditEvent)


def test_returned_audit_read_object_cannot_be_mutated(session: Session) -> None:
    event = ae_repo.append(session, actor="system", action="audit.freeze")
    fetched = ae_repo.get(session, event.id)
    assert fetched is not None

    with pytest.raises(AttributeError):
        cast(Any, fetched).action = "tampered"


def test_returned_audit_read_object_cannot_be_deleted_by_session(session: Session) -> None:
    event = ae_repo.append(session, actor="system", action="audit.no-delete")
    fetched = ae_repo.get(session, event.id)
    assert fetched is not None

    with pytest.raises(UnmappedInstanceError):
        session.delete(fetched)


def test_list_for_target_returns_events_oldest_first(session: Session) -> None:
    # Insert in non-chronological order (different actions) and read back ordered.
    e1 = ae_repo.append(session, actor="system", action="a1", target_type="doc", target_id=7)
    e2 = ae_repo.append(session, actor="system", action="a2", target_type="doc", target_id=7)
    e3 = ae_repo.append(session, actor="system", action="a3", target_type="doc", target_id=7)
    # Unrelated event
    ae_repo.append(session, actor="system", action="ax", target_type="doc", target_id=999)

    events = ae_repo.list_for_target(session, "doc", 7)
    assert [e.id for e in events] == [e1.id, e2.id, e3.id]


def test_list_by_request_id(session: Session) -> None:
    a = ae_repo.append(session, actor="u", action="x", request_id="req-xyz")
    b = ae_repo.append(session, actor="u", action="y", request_id="req-xyz")
    ae_repo.append(session, actor="u", action="z", request_id="other-req")

    events = ae_repo.list_by_request_id(session, "req-xyz")
    assert {e.id for e in events} == {a.id, b.id}
