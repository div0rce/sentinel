"""``GET /dashboard/{volume,categories,confidence,sla}`` — KPI feeds for the M8 UI.

Each endpoint returns a Recharts-friendly array of records with stable, descriptive
keys. The shapes are intentionally narrow (one chart, one endpoint) so the frontend
can pass them straight to Recharts without a transform layer; renaming a field in
the API immediately tightens the typed API client and the chart component together.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.models import Document, Extraction, WorkflowItem, WorkflowStatus

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


class Kpi(BaseModel):
    """One operational KPI tile for the dashboard header.

    ``value``/``delta`` are the raw numbers (stable to assert on and to re-format);
    ``display``/``delta_display`` are the server-rendered strings the UI shows verbatim.
    ``direction`` drives the up/down/flat color (up=success, down=danger, flat=muted) and
    is keyed purely off the sign of ``delta`` — matching the design system's KPI semantics.
    """

    key: str
    label: str
    value: float
    display: str
    delta: float | None = None
    delta_display: str | None = None
    direction: Literal["up", "down", "flat"]


class KpiResponse(BaseModel):
    kpis: list[Kpi]
    threshold_hours: int = Field(ge=1)
    generated_at: str  # ISO-8601 UTC; lets the UI footnote show a real refresh time


# --- helpers ------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _direction(delta: float | None, *, eps: float = 1e-9) -> Literal["up", "down", "flat"]:
    """Color direction from the sign of a delta; ``None`` or near-zero reads as flat."""
    if delta is None or abs(delta) <= eps:
        return "flat"
    return "up" if delta > 0 else "down"


def _mean(values: list[float]) -> float | None:
    """Arithmetic mean, or ``None`` for an empty list (so callers can omit, not fake, it)."""
    return sum(values) / len(values) if values else None


def _workflow_counts(
    session: Session, *, since: datetime | None = None, until: datetime | None = None
) -> tuple[int, int]:
    """Return ``(auto_approved, total)`` workflow-item counts in the optional ``[since, until)``
    creation window (open bounds when an endpoint is ``None``)."""
    clauses = []
    if since is not None:
        clauses.append(WorkflowItem.created_at >= since)
    if until is not None:
        clauses.append(WorkflowItem.created_at < until)
    total_stmt = select(func.count(WorkflowItem.id))
    approved_stmt = select(func.count(WorkflowItem.id)).where(
        WorkflowItem.status == WorkflowStatus.AUTO_APPROVED
    )
    if clauses:
        total_stmt = total_stmt.where(*clauses)
        approved_stmt = approved_stmt.where(*clauses)
    total = int(session.scalar(total_stmt) or 0)
    approved = int(session.scalar(approved_stmt) or 0)
    return approved, total


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
    start_at = datetime.combine(start, time.min, tzinfo=UTC)
    day = func.date_trunc("day", func.timezone("UTC", Extraction.created_at))
    stmt = (
        select(day.label("day"), func.count(Extraction.id).label("count"))
        .where(Extraction.created_at >= start_at)
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


@router.get("/kpis", response_model=KpiResponse)
def get_kpis(
    session: Annotated[Session, Depends(get_session)],
    threshold_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> KpiResponse:
    """Four operational KPIs for the dashboard header.

    Every figure is derived from real rows. Deltas compare the last 24h against the
    preceding 24h and are reported as ``None`` whenever a comparison window has no data,
    so the UI shows nothing fabricated. ``generated_at`` is a real UTC timestamp.
    """
    now = _utcnow()
    last_24h = now - timedelta(hours=24)
    prev_24h = now - timedelta(hours=48)

    # 1) Docs ingested — total, plus how many landed in the last 24h.
    total_docs = int(session.scalar(select(func.count(Document.id))) or 0)
    docs_24h = int(
        session.scalar(select(func.count(Document.id)).where(Document.created_at >= last_24h)) or 0
    )
    docs_kpi = Kpi(
        key="docs_ingested",
        label="Docs ingested",
        value=float(total_docs),
        display=f"{total_docs:,}",
        delta=float(docs_24h),
        delta_display=f"+{docs_24h} (24h)",
        direction=_direction(float(docs_24h)),
    )

    # 2) Auto-approved rate — share of all workflow items auto-approved, with the delta in
    #    percentage points between the last-24h and preceding-24h cohorts.
    approved_all, total_all = _workflow_counts(session)
    rate_all = approved_all / total_all if total_all else 0.0
    approved_last, total_last = _workflow_counts(session, since=last_24h)
    approved_prev, total_prev = _workflow_counts(session, since=prev_24h, until=last_24h)
    rate_delta: float | None = None
    if total_last and total_prev:
        rate_delta = (approved_last / total_last) - (approved_prev / total_prev)
    auto_kpi = Kpi(
        key="auto_approved_rate",
        label="Auto-approved",
        value=rate_all,
        display=f"{rate_all * 100:.1f}%",
        delta=rate_delta,
        delta_display=(f"{rate_delta * 100:+.1f}pp" if rate_delta is not None else None),
        direction=_direction(rate_delta),
    )

    # 3) Avg confidence — mean of every per-field confidence value, with a 24h-vs-prior delta.
    rows = session.execute(select(Extraction.created_at, Extraction.field_confidence)).all()
    all_vals: list[float] = []
    last_vals: list[float] = []
    prev_vals: list[float] = []
    for created_at, field_confidence in rows:
        if not isinstance(field_confidence, dict):
            continue
        for value in field_confidence.values():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            all_vals.append(v)
            if created_at is None:
                continue
            if created_at >= last_24h:
                last_vals.append(v)
            elif prev_24h <= created_at < last_24h:
                prev_vals.append(v)
    mean_all = _mean(all_vals)
    mean_last = _mean(last_vals)
    mean_prev = _mean(prev_vals)
    conf_delta = mean_last - mean_prev if mean_last is not None and mean_prev is not None else None
    conf_kpi = Kpi(
        key="avg_confidence",
        label="Avg confidence",
        value=mean_all if mean_all is not None else 0.0,
        display=f"{mean_all:.3f}" if mean_all is not None else "—",
        delta=conf_delta,
        delta_display=(f"{conf_delta:+.3f}" if conf_delta is not None else None),
        direction=_direction(conf_delta),
    )

    # 4) SLA at risk — items past the threshold over the needs-review total (reuses /sla).
    sla = get_sla(session, threshold_hours=threshold_hours)
    sla_kpi = Kpi(
        key="sla_at_risk",
        label="SLA at risk",
        value=float(sla.over_sla),
        display=f"{sla.over_sla} / {sla.total_needs_review}",
        delta=None,
        delta_display=f"threshold {threshold_hours}h",
        direction="flat",
    )

    return KpiResponse(
        kpis=[docs_kpi, auto_kpi, conf_kpi, sla_kpi],
        threshold_hours=threshold_hours,
        generated_at=now.isoformat(),
    )


# Re-export the literal type used by the frontend's API client so a future schema
# evolution surfaces in one place.
SlaThresholdLiteral = Literal[1, 4, 24, 168, 720]
