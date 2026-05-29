"""``GET /review`` and ``POST /review/{id}/approve|reject`` — human-in-the-loop.

The review router is the **only** path that legitimately transitions a workflow
item across the boundaries that :func:`backend.app.workflow.apply_routing` refuses.
Approving an item that the rule engine would otherwise leave in ``needs_review``
or even ``rejected`` is a human decision and must be recorded as an audit event;
this router does both atomically.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.audit import emit_review_decision
from backend.app.db import get_session
from backend.app.models import WorkflowStatus
from backend.app.repositories import workflow_items as workflow_items_repo

router = APIRouter(prefix="/review", tags=["review"])


# --- request / response schemas -------------------------------------------------------


class ReviewItem(BaseModel):
    """A single workflow item exposed in the review queue."""

    id: int
    extraction_id: int
    status: Literal["auto_approved", "needs_review", "rejected"]
    reason: str | None = None
    idempotency_key: str
    created_at: str
    updated_at: str


class ReviewQueueResponse(BaseModel):
    items: list[ReviewItem]


class ReviewDecisionRequest(BaseModel):
    """Body for approve / reject. Authentication-derived actor arrives in M8."""

    actor: str = Field(..., min_length=1, max_length=256)
    note: str | None = Field(default=None, max_length=4000)


class ReviewDecisionResponse(BaseModel):
    id: int
    extraction_id: int
    status: Literal["auto_approved", "rejected"]
    audit_event_id: int


# --- helpers --------------------------------------------------------------------------


def _to_review_item(item) -> ReviewItem:  # type: ignore[no-untyped-def]
    return ReviewItem(
        id=item.id,
        extraction_id=item.extraction_id,
        status=item.status.value,
        reason=item.reason,
        idempotency_key=item.idempotency_key,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


# --- handlers -------------------------------------------------------------------------


@router.get("", response_model=ReviewQueueResponse)
def get_queue(
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
    offset: int = 0,
) -> ReviewQueueResponse:
    """Return workflow items currently awaiting human review (``needs_review``)."""
    if limit < 1 or limit > 200:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "limit must be in [1, 200]")
    if offset < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "offset must be >= 0")
    rows = workflow_items_repo.list_by_status(
        session, WorkflowStatus.NEEDS_REVIEW, limit=limit, offset=offset
    )
    return ReviewQueueResponse(items=[_to_review_item(r) for r in rows])


def _decide(
    session: Session,
    *,
    item_id: int,
    target_status: WorkflowStatus,
    decision: Literal["approved", "rejected"],
    body: ReviewDecisionRequest,
) -> ReviewDecisionResponse:
    item = workflow_items_repo.get(session, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow_items.id={item_id} not found")
    if item.status is not WorkflowStatus.NEEDS_REVIEW:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"workflow_items.id={item_id} is {item.status.value}, not needs_review; "
            "only items in needs_review can be approved or rejected via this endpoint",
        )

    prior_status = item.status
    updated = workflow_items_repo.set_status(
        session,
        item_id,
        status=target_status,
        reason=f"human:{decision}",
    )
    if updated is None:  # pragma: no cover - we just loaded it
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow_items.id={item_id} disappeared")

    audit = emit_review_decision(
        session,
        workflow_item=updated,
        prior_status=prior_status,
        decision=decision,
        actor=body.actor,
        note=body.note,
    )
    session.commit()
    return ReviewDecisionResponse(
        id=updated.id,
        extraction_id=updated.extraction_id,
        status=updated.status.value,  # type: ignore[arg-type]
        audit_event_id=audit.id,
    )


@router.post("/{item_id}/approve", response_model=ReviewDecisionResponse)
def post_approve(
    item_id: int,
    body: ReviewDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ReviewDecisionResponse:
    """Human approval transition: ``needs_review → auto_approved``.

    This is the only legitimate path for that transition; the rule engine refuses
    it via :class:`backend.app.workflow.IllegalTransition`. Records exactly one
    ``review.approved`` audit event.
    """
    return _decide(
        session,
        item_id=item_id,
        target_status=WorkflowStatus.AUTO_APPROVED,
        decision="approved",
        body=body,
    )


@router.post("/{item_id}/reject", response_model=ReviewDecisionResponse)
def post_reject(
    item_id: int,
    body: ReviewDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ReviewDecisionResponse:
    """Human rejection transition: ``needs_review → rejected``.

    Records exactly one ``review.rejected`` audit event.
    """
    return _decide(
        session,
        item_id=item_id,
        target_status=WorkflowStatus.REJECTED,
        decision="rejected",
        body=body,
    )
