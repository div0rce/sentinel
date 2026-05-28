"""Generate Sentinel's synthetic sample corpus.

Output files are written to ``data/sample/`` and committed. The generator is
deterministic (seeded ``random.Random``) so re-running on a clean tree produces
byte-identical files — easy to review in PRs and easy to verify reproducibility.

All content is fictional. Names, IDs, dates, and dollar values are synthetic; nothing
here represents real people, companies, or events.

Run from the repo root::

    uv run python scripts/gen_synthetic_corpus.py
"""

from __future__ import annotations

import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "sample"
SEED = 20260528


# ---- corpus templates ----------------------------------------------------------------

VENDORS = [
    "Acme Synthetic Co.",
    "Northwind Logistics",
    "Globex Industrial",
    "Initech Components",
    "Hooli Cloud Services",
    "Stark Manufacturing",
    "Wayne Heavy Industries",
    "Soylent Mfg.",
]

LOCATIONS = ["Plant 4", "Warehouse B", "Distribution Center 12", "Lab North", "Yard 7"]

INCIDENT_KINDS = [
    "unscheduled downtime",
    "minor hydraulic leak",
    "conveyor belt jam",
    "pressure regulator anomaly",
    "soft spec drift",
    "barcode scanner failure",
]

POLICY_TOPICS = [
    "supplier onboarding",
    "incident response escalation",
    "change-control approval",
    "data-retention",
    "quality sampling",
]


def _make_invoice(rng: random.Random, idx: int) -> tuple[str, str]:
    vendor = rng.choice(VENDORS)
    invoice_no = f"INV-{2026000 + idx}"
    line_count = rng.randint(2, 5)
    lines: list[str] = []
    total = 0.0
    for _ in range(line_count):
        qty = rng.randint(5, 200)
        unit = round(rng.uniform(2.50, 320.00), 2)
        amount = round(qty * unit, 2)
        total += amount
        lines.append(
            f"- SKU {rng.randint(10000, 99999)}: {qty} units @ ${unit:,.2f} = ${amount:,.2f}"
        )
    issue_date = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    net_terms = rng.choice([15, 30, 45, 60])
    body = "\n".join(
        [
            f"# Invoice {invoice_no}",
            "",
            f"**Vendor:** {vendor}",
            f"**Issue date:** {issue_date}",
            f"**Net terms:** Net {net_terms}",
            "",
            "## Line items",
            "",
            *lines,
            "",
            f"**Subtotal:** ${total:,.2f}",
            f"**Tax (8.25%):** ${total * 0.0825:,.2f}",
            f"**Total due:** ${total * 1.0825:,.2f}",
            "",
            "> This invoice is synthetic test data for the Sentinel project. It does not",
            "> represent any real transaction, vendor, or amount.",
            "",
        ]
    )
    return invoice_no, body


def _make_incident(rng: random.Random, idx: int) -> tuple[str, str]:
    incident_no = f"INC-{700 + idx:04d}"
    kind = rng.choice(INCIDENT_KINDS)
    location = rng.choice(LOCATIONS)
    duration_min = rng.randint(8, 240)
    detected_by = rng.choice(["operator on shift", "automated SCADA alert", "QA spot check"])
    detected_at = (
        f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T"
        f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}Z"
    )
    sop = rng.randint(100, 999)
    initial_hypothesis = rng.choice(
        [
            "worn seal",
            "calibration drift",
            "operator misconfiguration",
            "ambient temperature spike",
        ]
    )
    root_cause = rng.choice(
        ["mechanical wear", "process variance", "instrumentation drift", "environmental factor"]
    )
    body = "\n".join(
        [
            f"# Incident report {incident_no}",
            "",
            f"**Kind:** {kind}",
            f"**Location:** {location}",
            f"**Detected at:** {detected_at}",
            f"**Duration:** {duration_min} minutes",
            f"**Detected by:** {detected_by}",
            "",
            "## Narrative",
            "",
            f"On the date and time above, a {kind} was reported at {location}. The line was",
            f"paused per standard operating procedure SOP-{sop}. Initial diagnostics suggested",
            f"{initial_hypothesis}. A senior technician was dispatched and the issue was resolved",
            "after replacing the affected component and verifying ten consecutive nominal cycles.",
            "",
            "## Root cause",
            "",
            f"Provisional root cause is recorded as {root_cause}. A formal RCA is scheduled",
            "within five business days.",
            "",
            "## Disposition",
            "",
            "Production resumed at the next shift handover with no quality holds applied.",
            "This report is synthetic and used solely for Sentinel development.",
            "",
        ]
    )
    return incident_no, body


def _make_policy(rng: random.Random, idx: int) -> tuple[str, str]:
    policy_no = f"POL-{200 + idx:03d}"
    topic = rng.choice(POLICY_TOPICS)
    review_months = rng.choice([6, 12, 18, 24])
    effective = f"2026-{rng.randint(1, 12):02d}-01"
    threshold_low = rng.randint(5, 25) * 1000
    threshold_mid_low = rng.randint(25, 100) * 1000
    threshold_mid_high = rng.randint(100, 500) * 1000
    sample_pct = rng.randint(5, 25)
    body = "\n".join(
        [
            f"# Policy {policy_no}: {topic.title()}",
            "",
            "**Owner:** Office of the Chief Compliance Officer (synthetic)",
            f"**Effective:** {effective}",
            f"**Review cadence:** every {review_months} months",
            "",
            "## Purpose",
            "",
            f"This policy establishes baseline expectations for {topic} across all operating",
            "units. It applies to employees, contractors, and authorized third parties.",
            "",
            "## Requirements",
            "",
            "1. All in-scope activities MUST be recorded in the platform of record within",
            "   one business day.",
            "2. Approval thresholds escalate as follows:",
            f"   - Up to ${threshold_low:,}: line manager",
            f"   - ${threshold_mid_low:,} to ${threshold_mid_high:,}: department head",
            "   - Above that: executive sponsor with audit-committee notification.",
            "3. Deviations require a written exception with a documented compensating",
            "   control and a re-review date within 90 days.",
            "",
            "## Audit and review",
            "",
            f"The internal audit function samples {sample_pct}% of in-scope records each",
            "quarter. Findings are tracked in the workflow queue and closed only with a",
            "documented disposition. This policy is synthetic content for Sentinel development",
            "and does not bind any real organization.",
            "",
        ]
    )
    return policy_no, body


# ---- driver --------------------------------------------------------------------------


def _slug(prefix: str, name: str) -> str:
    safe = name.lower().replace(" ", "_").replace("/", "_")
    return f"{prefix}_{safe}.md"


def main() -> None:
    rng = random.Random(SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe previously generated synthetic files (keep README.md and any non-corpus
    # files). We only delete files matching our generated naming scheme.
    for pattern in ("invoice_*.md", "incident_*.md", "policy_*.md"):
        for existing in OUTPUT_DIR.glob(pattern):
            existing.unlink()

    written: list[Path] = []

    for i in range(5):
        name, body = _make_invoice(rng, i)
        path = OUTPUT_DIR / _slug("invoice", name)
        path.write_text(body, encoding="utf-8")
        written.append(path)

    for i in range(5):
        name, body = _make_incident(rng, i)
        path = OUTPUT_DIR / _slug("incident", name)
        path.write_text(body, encoding="utf-8")
        written.append(path)

    for i in range(4):
        name, body = _make_policy(rng, i)
        path = OUTPUT_DIR / _slug("policy", name)
        path.write_text(body, encoding="utf-8")
        written.append(path)

    print(f"wrote {len(written)} files to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    for path in sorted(written):
        print(f"  {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
