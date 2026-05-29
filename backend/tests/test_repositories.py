"""Tests for the per-aggregate repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import Document, WorkflowStatus
from backend.app.repositories import (
    chunks as chunks_repo,
)
from backend.app.repositories import (
    documents as documents_repo,
)
from backend.app.repositories import (
    extractions as extractions_repo,
)
from backend.app.repositories import (
    workflow_items as workflow_items_repo,
)


def _make_document(session: Session, *, hash_suffix: str = "00") -> Document:
    return documents_repo.create(
        session, hash="d" + hash_suffix.ljust(63, "0"), source=f"src-{hash_suffix}"
    )


# -- documents ---------------------------------------------------------------------


def test_documents_create_get_and_get_by_hash(session: Session) -> None:
    doc = _make_document(session, hash_suffix="01")
    assert doc.id is not None

    fetched = documents_repo.get(session, doc.id)
    assert fetched is not None
    assert fetched.hash == doc.hash

    by_hash = documents_repo.get_by_hash(session, doc.hash)
    assert by_hash is not None
    assert by_hash.id == doc.id

    assert documents_repo.get(session, 99_999_999) is None
    assert documents_repo.get_by_hash(session, "nope") is None


def test_documents_list_all_orders_and_paginates(session: Session) -> None:
    for i in range(3):
        _make_document(session, hash_suffix=f"l{i}")
    items = documents_repo.list_all(session, limit=2)
    assert len(items) == 2
    assert items[0].id < items[1].id


# -- chunks ------------------------------------------------------------------------


def test_chunks_bulk_insert_and_list_for_document(session: Session) -> None:
    doc = _make_document(session, hash_suffix="c1")
    inserted = chunks_repo.bulk_insert(
        session,
        document_id=doc.id,
        chunks=[
            {"ord": 0, "text": "alpha", "token_count": 1},
            {"ord": 1, "text": "beta", "token_count": 1},
        ],
    )
    assert len(inserted) == 2
    assert all(c.id is not None for c in inserted)

    listed = chunks_repo.list_for_document(session, doc.id)
    assert [c.ord for c in listed] == [0, 1]


def test_chunks_bulk_insert_rejects_duplicate_ord(session: Session) -> None:
    doc = _make_document(session, hash_suffix="c2")
    chunks_repo.bulk_insert(
        session,
        document_id=doc.id,
        chunks=[{"ord": 0, "text": "x", "token_count": 1}],
    )
    with pytest.raises(IntegrityError):
        chunks_repo.bulk_insert(
            session,
            document_id=doc.id,
            chunks=[{"ord": 0, "text": "x", "token_count": 1}],
        )


# -- extractions -------------------------------------------------------------------


def test_extractions_create_and_list_for_document_newest_first(session: Session) -> None:
    doc = _make_document(session, hash_suffix="e1")
    e1 = extractions_repo.create(
        session,
        document_id=doc.id,
        schema_name="invoice",
        payload={"v": 1},
        field_confidence={"v": 0.9},
        field_citations={"v": [1]},
    )
    e2 = extractions_repo.create(
        session,
        document_id=doc.id,
        schema_name="invoice",
        payload={"v": 2},
    )
    listed = extractions_repo.list_for_document(session, doc.id)
    assert [e.id for e in listed] == [e2.id, e1.id]


# -- workflow_items ----------------------------------------------------------------


def test_workflow_items_create_and_lookups(session: Session) -> None:
    doc = _make_document(session, hash_suffix="w1")
    extraction = extractions_repo.create(session, document_id=doc.id, schema_name="x", payload={})

    item = workflow_items_repo.create(
        session,
        extraction_id=extraction.id,
        status=WorkflowStatus.NEEDS_REVIEW,
        idempotency_key="route-1",
        reason="below threshold",
    )

    by_id = workflow_items_repo.get(session, item.id)
    assert by_id is not None
    assert by_id.id == item.id

    by_key = workflow_items_repo.get_by_idempotency_key(session, "route-1")
    assert by_key is not None
    assert by_key.id == item.id
    assert workflow_items_repo.get_by_idempotency_key(session, "missing") is None

    listed = workflow_items_repo.list_by_status(session, WorkflowStatus.NEEDS_REVIEW)
    assert any(wi.id == item.id for wi in listed)


def test_workflow_items_set_status_transitions_and_returns_none_for_missing(
    session: Session,
) -> None:
    doc = _make_document(session, hash_suffix="w2")
    extraction = extractions_repo.create(session, document_id=doc.id, schema_name="x", payload={})
    item = workflow_items_repo.create(
        session,
        extraction_id=extraction.id,
        status=WorkflowStatus.NEEDS_REVIEW,
        idempotency_key="route-2",
    )

    updated = workflow_items_repo.set_status(
        session, item.id, status=WorkflowStatus.AUTO_APPROVED, reason="reviewed"
    )
    assert updated is not None
    assert updated.status is WorkflowStatus.AUTO_APPROVED
    assert updated.reason == "reviewed"

    assert (
        workflow_items_repo.set_status(session, 99_999_999, status=WorkflowStatus.REJECTED) is None
    )


def test_workflow_items_transition_from_status_is_conditional(session: Session) -> None:
    doc = _make_document(session, hash_suffix="w3")
    extraction = extractions_repo.create(session, document_id=doc.id, schema_name="x", payload={})
    item = workflow_items_repo.create(
        session,
        extraction_id=extraction.id,
        status=WorkflowStatus.NEEDS_REVIEW,
        idempotency_key="route-3",
    )

    updated = workflow_items_repo.transition_from_status(
        session,
        item.id,
        expected_status=WorkflowStatus.NEEDS_REVIEW,
        target_status=WorkflowStatus.REJECTED,
        reason="human:rejected",
    )
    assert updated is not None
    assert updated.status is WorkflowStatus.REJECTED
    assert updated.reason == "human:rejected"

    stale = workflow_items_repo.transition_from_status(
        session,
        item.id,
        expected_status=WorkflowStatus.NEEDS_REVIEW,
        target_status=WorkflowStatus.AUTO_APPROVED,
        reason="human:approved",
    )
    assert stale is None
    refreshed = workflow_items_repo.get(session, item.id)
    assert refreshed is not None
    assert refreshed.status is WorkflowStatus.REJECTED
