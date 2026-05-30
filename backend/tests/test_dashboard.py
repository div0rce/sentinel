"""Tests for the M8 dashboard router."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.main import app
from backend.app.models import Chunk, Document, Extraction, WorkflowItem, WorkflowStatus
from backend.app.routers import dashboard as dashboard_router


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _make_extraction(
    session: Session,
    *,
    hash_suffix: str,
    schema_name: str = "invoice",
    field_confidence: dict[str, float] | None = None,
    created_at: datetime | None = None,
) -> Extraction:
    doc = Document(
        hash="d" + hash_suffix.ljust(63, "0"),
        source=f"test://{hash_suffix}",
    )
    session.add(doc)
    session.flush()
    extraction = Extraction(
        document_id=doc.id,
        schema_name=schema_name,
        payload={k: f"v-{k}" for k in (field_confidence or {})},
        field_confidence=field_confidence or {},
        field_citations={k: [doc.id] for k in (field_confidence or {})},
    )
    session.add(extraction)
    session.flush()
    if created_at is not None:
        extraction.created_at = created_at
        session.flush()
    return extraction


def _make_workflow_item(
    session: Session,
    *,
    extraction_id: int,
    idem_suffix: str,
    status: WorkflowStatus = WorkflowStatus.NEEDS_REVIEW,
    age_hours: float = 0.0,
) -> WorkflowItem:
    item = WorkflowItem(
        extraction_id=extraction_id,
        status=status,
        idempotency_key=f"sla-{idem_suffix}-{extraction_id}",
        reason="seeded",
    )
    session.add(item)
    session.flush()
    if age_hours > 0:
        item.created_at = datetime.now(UTC) - timedelta(hours=age_hours)
        session.flush()
    return item


# --- /dashboard/volume --------------------------------------------------------------


def test_volume_returns_backfilled_zero_days(client: TestClient) -> None:
    """An empty corpus must still return ``days`` points, all zero."""
    resp = client.get("/dashboard/volume?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["points"]) == 7
    assert all(p["count"] == 0 for p in body["points"])


def test_volume_counts_extractions_per_day(client: TestClient, session: Session) -> None:
    today = datetime.now(UTC)
    yesterday = today - timedelta(days=1)
    _make_extraction(session, hash_suffix="vt1", field_confidence={"a": 0.9}, created_at=today)
    _make_extraction(session, hash_suffix="vt2", field_confidence={"a": 0.9}, created_at=today)
    _make_extraction(session, hash_suffix="vt3", field_confidence={"a": 0.9}, created_at=yesterday)

    resp = client.get("/dashboard/volume?days=3")
    assert resp.status_code == 200
    points = {p["date"]: p["count"] for p in resp.json()["points"]}
    assert points[today.date().isoformat()] == 2
    assert points[yesterday.date().isoformat()] == 1


def test_volume_groups_by_utc_day_independent_of_db_timezone(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dashboard_router, "_utcnow", lambda: datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    )
    session.execute(text("SET LOCAL TIME ZONE 'America/Los_Angeles'"))
    _make_extraction(
        session,
        hash_suffix="vutc",
        field_confidence={"a": 0.9},
        created_at=datetime(2026, 5, 29, 1, 30, tzinfo=UTC),
    )

    resp = client.get("/dashboard/volume?days=1")

    assert resp.status_code == 200
    assert resp.json()["points"] == [{"date": "2026-05-29", "count": 1}]


def test_volume_rejects_invalid_days(client: TestClient) -> None:
    assert client.get("/dashboard/volume?days=0").status_code == 422
    assert client.get("/dashboard/volume?days=-1").status_code == 422
    assert client.get("/dashboard/volume?days=400").status_code == 422


# --- /dashboard/categories ----------------------------------------------------------


def test_categories_returns_count_per_schema(client: TestClient, session: Session) -> None:
    _make_extraction(session, hash_suffix="c1", schema_name="invoice", field_confidence={"a": 0.9})
    _make_extraction(session, hash_suffix="c2", schema_name="invoice", field_confidence={"a": 0.9})
    _make_extraction(session, hash_suffix="c3", schema_name="receipt", field_confidence={"a": 0.9})

    resp = client.get("/dashboard/categories")
    assert resp.status_code == 200
    points = {p["schema_name"]: p["count"] for p in resp.json()["points"]}
    assert points["invoice"] == 2
    assert points["receipt"] == 1
    # Ordering: counts descending; ties broken alphabetically.
    schemas = [p["schema_name"] for p in resp.json()["points"]]
    assert schemas == sorted(schemas, key=lambda s: (-points[s], s))


def test_categories_empty_corpus(client: TestClient) -> None:
    resp = client.get("/dashboard/categories")
    assert resp.status_code == 200
    assert resp.json() == {"points": []}


# --- /dashboard/confidence ----------------------------------------------------------


def test_confidence_buckets_have_ten_bins(client: TestClient) -> None:
    resp = client.get("/dashboard/confidence")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["buckets"]) == 10
    assert body["total_fields"] == 0
    # Boundaries cover [0, 1] in 0.1-wide bins.
    assert body["buckets"][0]["lower"] == 0.0
    assert body["buckets"][9]["upper"] == 1.0


def test_confidence_buckets_count_per_field_values(client: TestClient, session: Session) -> None:
    _make_extraction(
        session,
        hash_suffix="cf1",
        field_confidence={"a": 0.05, "b": 0.55, "c": 0.95},
    )
    _make_extraction(session, hash_suffix="cf2", field_confidence={"a": 0.55, "b": 1.0})

    resp = client.get("/dashboard/confidence")
    body = resp.json()
    assert body["total_fields"] == 5

    # Bucket 0 (0.0–0.1): one value 0.05.
    assert body["buckets"][0]["count"] == 1
    # Bucket 5 (0.5–0.6): two values (0.55 each).
    assert body["buckets"][5]["count"] == 2
    # Bucket 9 (0.9–1.0): two values (0.95 and 1.0; 1.0 lands in last bucket).
    assert body["buckets"][9]["count"] == 2


# --- /dashboard/sla -----------------------------------------------------------------


def test_sla_zero_when_no_needs_review(client: TestClient, session: Session) -> None:
    extraction = _make_extraction(session, hash_suffix="sla0", field_confidence={"a": 0.95})
    _make_workflow_item(
        session,
        extraction_id=extraction.id,
        idem_suffix="z",
        status=WorkflowStatus.AUTO_APPROVED,
    )
    resp = client.get("/dashboard/sla")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_needs_review"] == 0
    assert body["over_sla"] == 0
    assert {b["label"] for b in body["buckets"]} == {"<1h", "1\u20134h", "4\u201324h", ">24h"}


def test_sla_buckets_count_aging_items(client: TestClient, session: Session) -> None:
    extraction = _make_extraction(session, hash_suffix="sla1", field_confidence={"a": 0.4})
    _make_workflow_item(session, extraction_id=extraction.id, idem_suffix="now", age_hours=0.1)
    _make_workflow_item(session, extraction_id=extraction.id, idem_suffix="2h", age_hours=2.0)
    _make_workflow_item(session, extraction_id=extraction.id, idem_suffix="10h", age_hours=10.0)
    _make_workflow_item(session, extraction_id=extraction.id, idem_suffix="48h", age_hours=48.0)

    resp = client.get("/dashboard/sla?threshold_hours=24")
    body = resp.json()
    counts = {b["label"]: b["count"] for b in body["buckets"]}
    assert counts == {"<1h": 1, "1\u20134h": 1, "4\u201324h": 1, ">24h": 1}
    assert body["total_needs_review"] == 4
    assert body["over_sla"] == 1  # the 48h item is past threshold; 10h is not


def test_sla_rejects_invalid_threshold(client: TestClient) -> None:
    assert client.get("/dashboard/sla?threshold_hours=0").status_code == 422
    assert client.get("/dashboard/sla?threshold_hours=-1").status_code == 422
    assert client.get("/dashboard/sla?threshold_hours=10000").status_code == 422


# --- /dashboard/kpis ----------------------------------------------------------------


def test_kpis_empty_corpus(client: TestClient) -> None:
    """No rows: four KPIs, honest zeros, and no fabricated deltas."""
    resp = client.get("/dashboard/kpis")
    assert resp.status_code == 200
    body = resp.json()
    kpis = {k["key"]: k for k in body["kpis"]}
    assert set(kpis) == {"docs_ingested", "auto_approved_rate", "avg_confidence", "sla_at_risk"}

    assert kpis["docs_ingested"]["display"] == "0"
    assert kpis["auto_approved_rate"]["display"] == "0.0%"
    assert kpis["avg_confidence"]["display"] == "—"  # em dash: no fields, no fake number
    assert kpis["sla_at_risk"]["display"] == "0 / 0"

    # Deltas that need a comparison window are omitted (None), not invented.
    assert kpis["auto_approved_rate"]["delta"] is None
    assert kpis["avg_confidence"]["delta"] is None
    assert all(k["direction"] == "flat" for k in kpis.values())


def test_kpis_values_and_formatting(client: TestClient, session: Session) -> None:
    now = datetime.now(UTC)
    # Two extractions (=> two documents) created now; per-field confidences mean to 0.800.
    _make_extraction(
        session, hash_suffix="kv1", field_confidence={"a": 0.80, "b": 0.90}, created_at=now
    )
    ex2 = _make_extraction(session, hash_suffix="kv2", field_confidence={"a": 0.70}, created_at=now)
    # Workflow mix: 3 auto-approved + 1 needs_review => 75.0% auto-approved.
    for i in range(3):
        _make_workflow_item(
            session, extraction_id=ex2.id, idem_suffix=f"a{i}", status=WorkflowStatus.AUTO_APPROVED
        )
    _make_workflow_item(
        session, extraction_id=ex2.id, idem_suffix="nr", status=WorkflowStatus.NEEDS_REVIEW
    )

    kpis = {k["key"]: k for k in client.get("/dashboard/kpis").json()["kpis"]}

    assert kpis["docs_ingested"]["value"] == 2.0
    assert kpis["docs_ingested"]["display"] == "2"
    assert kpis["docs_ingested"]["delta"] == 2.0  # both landed within the last 24h
    assert kpis["docs_ingested"]["delta_display"] == "+2 (24h)"

    assert kpis["avg_confidence"]["value"] == pytest.approx(0.8)
    assert kpis["avg_confidence"]["display"] == "0.800"

    assert kpis["auto_approved_rate"]["value"] == pytest.approx(0.75)
    assert kpis["auto_approved_rate"]["display"] == "75.0%"

    # The single needs_review item is age ~0, so it is not yet over the 24h threshold.
    assert kpis["sla_at_risk"]["display"] == "0 / 1"


def test_kpis_auto_approved_delta(client: TestClient, session: Session) -> None:
    """The auto-approved delta compares the last-24h cohort against the preceding 24h."""
    ext = _make_extraction(session, hash_suffix="kad", field_confidence={"a": 0.9})
    # Preceding 24–48h window: 2 items, 1 auto-approved => rate 0.50.
    _make_workflow_item(
        session,
        extraction_id=ext.id,
        idem_suffix="p1",
        status=WorkflowStatus.AUTO_APPROVED,
        age_hours=36,
    )
    _make_workflow_item(
        session,
        extraction_id=ext.id,
        idem_suffix="p2",
        status=WorkflowStatus.NEEDS_REVIEW,
        age_hours=36,
    )
    # Last-24h window: 4 items, 3 auto-approved => rate 0.75.
    for i in range(3):
        _make_workflow_item(
            session,
            extraction_id=ext.id,
            idem_suffix=f"l{i}",
            status=WorkflowStatus.AUTO_APPROVED,
            age_hours=2,
        )
    _make_workflow_item(
        session,
        extraction_id=ext.id,
        idem_suffix="lnr",
        status=WorkflowStatus.NEEDS_REVIEW,
        age_hours=2,
    )

    auto = next(
        k for k in client.get("/dashboard/kpis").json()["kpis"] if k["key"] == "auto_approved_rate"
    )
    assert auto["delta"] == pytest.approx(0.25)  # 0.75 - 0.50
    assert auto["delta_display"] == "+25.0pp"
    assert auto["direction"] == "up"


def test_kpis_rejects_invalid_threshold(client: TestClient) -> None:
    assert client.get("/dashboard/kpis?threshold_hours=0").status_code == 422
    assert client.get("/dashboard/kpis?threshold_hours=-1").status_code == 422
    assert client.get("/dashboard/kpis?threshold_hours=10000").status_code == 422


# --- shape sanity (frontend depends on these keys) ----------------------------------


def test_response_keys_match_frontend_contract(client: TestClient) -> None:
    """The frontend's typed API client mirrors these key sets one-to-one."""
    assert set(client.get("/dashboard/volume?days=1").json().keys()) == {"days", "points"}
    assert set(client.get("/dashboard/categories").json().keys()) == {"points"}
    conf = client.get("/dashboard/confidence").json()
    assert set(conf.keys()) == {"buckets", "total_fields"}
    assert set(conf["buckets"][0].keys()) == {"label", "lower", "upper", "count"}
    sla = client.get("/dashboard/sla").json()
    assert set(sla.keys()) == {"threshold_hours", "total_needs_review", "over_sla", "buckets"}
    assert set(sla["buckets"][0].keys()) == {"label", "count"}
    kpis = client.get("/dashboard/kpis").json()
    assert set(kpis.keys()) == {"kpis", "threshold_hours", "generated_at"}
    assert len(kpis["kpis"]) == 4
    assert set(kpis["kpis"][0].keys()) == {
        "key",
        "label",
        "value",
        "display",
        "delta",
        "delta_display",
        "direction",
    }


# --- silence the unused-import warning on Chunk (used by other test modules) -------

_ = Chunk
