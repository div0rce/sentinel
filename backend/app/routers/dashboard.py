"""``GET /dashboard/{volume,categories,confidence,sla}`` — KPI feeds for the M8 UI.

Each endpoint returns a Recharts-friendly array of records with stable, descriptive
keys. The shapes are intentionally narrow (one chart, one endpoint) so the frontend
can pass them straight to Recharts without a transform layer; renaming a field in
the API immediately tightens the typed API client and the chart component together.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.models import Extraction, WorkflowItem, WorkflowStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# --- response shapes ----------------------------------------------------------------


class VolumePoint(BaseModel):
    """One day of extraction volume."""

    date: str  # ISO YYYY-MM-DD (UTC)
    count: int = Field(ge=0)


class VolumeResponse(BaseModel):
    days: int = Field(ge=1)
    points: list[VolumePoint]


class CategoryPoint(BaseModel):
    schema_name: str
    count: int = Field(ge=0)


class CategoryResponse(BaseModel):
    points: list[CategoryPoint]


class ConfidenceBucket(BaseModel):
    """A 0.1-wide histogram bucket. ``label`` is "0.0–0.1" etc.; ``count`` is the
    total number of per-field confidence values that landed in this bucket across
    all extractions."""

    label: str
    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    count: int = Field(ge=0)


class ConfidenceResponse(BaseModel):
    buckets: list[ConfidenceBucket]
    total_fields: int = Field(ge=0)


class SlaBucket(BaseModel):
    """One age bucket for ``needs_review`` items."""

    label: str
    count: int = Field(ge=0)


class SlaResponse(BaseModel):
    threshold_hours: int = Field(ge=1)
    total_needs_review: int = Field(ge=0)
    over_sla: int = Field(ge=0)
    buckets: list[SlaBucket]


# --- helpers ------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Bucket boundaries for confidence: ten 0.1-wide bins covering [0.0, 1.0]. Values
# exactly equal to 1.0 land in the last bucket.
_CONF_BOUNDARIES: list[tuple[float, float]] = [
    (round(i / 10.0, 1), round((i + 1) / 10.0, 1)) for i in range(10)
]


def _confidence_bucket_index(value: float) -> int:
    if value <= 0.0:
        return 0
    if value >= 1.0:
        return 9
    return min(9, int(value * 10))


# --- endpoints ----------------------------------------------------------------------


@router.get("/volume", response_model=VolumeResponse)
def get_volume(
    session: Annotated[Session, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> VolumeResponse:
    """Return one row per UTC day for the last ``days`` days, oldest first."""
    start = _utcnow().date() - timedelta(days=days - 1)
    day = func.date_trunc("day", Extraction.created_at)
    stmt = (
        select(day.label("day"), func.count(Extraction.id).label("count"))
        .where(Extraction.created_at >= start)
        .group_by("day")
        .order_by("day")
    )
    rows = session.execute(stmt).all()
    by_date: dict[str, int] = {}
    for row in rows:
        date_value = row[0]
        if date_value is None:
            continue
        by_date[date_value.date().isoformat()] = int(row[1])

    # Backfill missing days with zero so the chart always has ``days`` points.
    points: list[VolumePoint] = []
    for offset in range(days):
        d = (start + timedelta(days=offset)).isoformat()
        points.append(VolumePoint(date=d, count=by_date.get(d, 0)))
    return VolumeResponse(days=days, points=points)


@router.get("/categories", response_model=CategoryResponse)
def get_categories(
    session: Annotated[Session, Depends(get_session)],
) -> CategoryResponse:
    """Extraction count per schema_name, descending."""
    stmt = (
        select(Extraction.schema_name, func.count(Extraction.id).label("count"))
        .group_by(Extraction.schema_name)
        .order_by(func.count(Extraction.id).desc(), Extraction.schema_name)
    )
    rows = session.execute(stmt).all()
    return CategoryResponse(points=[CategoryPoint(schema_name=r[0], count=int(r[1])) for r in rows])


@router.get("/confidence", response_model=ConfidenceResponse)
def get_confidence(
    session: Annotated[Session, Depends(get_session)],
) -> ConfidenceResponse:
    """Histogram of every per-field confidence value across all extractions."""
    rows = session.execute(select(Extraction.field_confidence)).all()
    counts = [0] * 10
    total = 0
    for (field_confidence,) in rows:
        if not isinstance(field_confidence, dict):
            continue
        for value in field_confidence.values():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            counts[_confidence_bucket_index(v)] += 1
            total += 1

    buckets = [
        ConfidenceBucket(
            label=f"{lower:.1f}\u2013{upper:.1f}",
            lower=lower,
            upper=upper,
            count=counts[i],
        )
        for i, (lower, upper) in enumerate(_CONF_BOUNDARIES)
    ]
    return ConfidenceResponse(buckets=buckets, total_fields=total)


_SLA_BUCKET_DEFS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<1h", None, 1.0),
    ("1–4h", 1.0, 4.0),
    ("4–24h", 4.0, 24.0),
    (">24h", 24.0, None),
)


@router.get("/sla", response_model=SlaResponse)
def get_sla(
    session: Annotated[Session, Depends(get_session)],
    threshold_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> SlaResponse:
    """Aging breakdown of ``needs_review`` items.

    ``over_sla`` counts items whose age exceeds ``threshold_hours``; the buckets
    are a fixed coarse breakdown <1h / 1–4h / 4–24h / >24h, regardless of the
    threshold value (the threshold is reported alongside so the UI can highlight
    the relevant bucket).
    """
    rows = session.execute(
        select(WorkflowItem.created_at).where(WorkflowItem.status == WorkflowStatus.NEEDS_REVIEW)
    ).all()
    now = _utcnow()
    threshold = timedelta(hours=threshold_hours)

    bucket_counts: Counter[str] = Counter()
    for label, _, _ in _SLA_BUCKET_DEFS:
        bucket_counts[label] = 0

    over = 0
    for (created_at,) in rows:
        if created_at is None:
            continue
        age = now - created_at
        hours = age.total_seconds() / 3600.0
        for label, lo, hi in _SLA_BUCKET_DEFS:
            if (lo is None or hours >= lo) and (hi is None or hours < hi):
                bucket_counts[label] += 1
                break
        if age >= threshold:
            over += 1

    if threshold_hours < 1:  # pragma: no cover - defensive; pydantic Query enforces >=1
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "threshold_hours must be >= 1")

    return SlaResponse(
        threshold_hours=threshold_hours,
        total_needs_review=sum(bucket_counts.values()),
        over_sla=over,
        buckets=[
            SlaBucket(label=label, count=bucket_counts[label]) for label, _, _ in _SLA_BUCKET_DEFS
        ],
    )


# Re-export the literal type used by the frontend's API client so a future schema
# evolution surfaces in one place.
SlaThresholdLiteral = Literal[1, 4, 24, 168, 720]
