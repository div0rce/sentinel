# Workflow engine

The workflow engine is Sentinel's differentiator. It maps a structured extraction —
plus its per-field confidence and any guardrail signals — to one of three statuses
(`auto_approved`, `needs_review`, `rejected`) **deterministically**, persists that
status **idempotently**, and lets you **replay** the decision at any time from
stored inputs.

The implementation lives in `backend/app/workflow.py`.

## Why deterministic

Three reasons, in order of importance:

1. **Audit defensibility.** Given a `workflow_items.id`, the M7 audit replay test
   reconstructs current state from `audit_events`; the routing rules are part of
   that reconstruction. If the rules were nondeterministic, the audit log would be
   ambiguous.
2. **Re-runs are safe.** Re-routing the same extraction must never duplicate work
   or accidentally revisit a rejected record. Determinism + idempotency keys are
   the mechanism.
3. **Eval reproducibility.** The M9 evaluation harness routes a labelled corpus
   and compares against ground truth. Deterministic routing means the eval result
   depends on the data and the rule version, not the wall clock.

## Decision rules

The rule layer is a single function `route(inputs: RoutingInputs) -> RoutingDecision`
with **no I/O**. Decisions follow a top-down precedence:

| #  | Condition                                                          | Status         | Reason                |
| -- | ------------------------------------------------------------------ | -------------- | --------------------- |
| 1  | Any guardrail flag in `{invalid_citation}`                         | `rejected`     | `guardrail_rejected`  |
| 2  | Any field's confidence `< confidence_review_threshold`             | `needs_review` | `low_confidence`      |
| 3  | Any other (non-rejecting) guardrail flag                           | `needs_review` | `guardrail_review`    |
| 4  | Otherwise                                                          | `auto_approved`| `ok`                  |

Rejection is **terminal at routing time**: rule #1 wins over rule #2 even if both
fire. This matches the M3 RAG citation-or-refuse posture (a fabricated citation is
a hard failure, not a degradation to review).

`RoutingInputs` carries everything the rule layer needs:

- `extraction_id: int`
- `schema_name: str`
- `field_confidence: Mapping[str, float]`
- `guardrail_flags: Sequence[str]`
- `confidence_review_threshold: float` (defaults to `Settings.confidence_review_threshold`,
  i.e. `0.75`)

`RoutingDecision` is a frozen dataclass with `status`, `reason`, `idempotency_key`,
and `routing_version`.

## Idempotency-key recipe

The key is the SHA-256 hex digest of a canonical join of three values:

```
sha256(f"{extraction_id}|{schema_name}|{routing_version}")
```

What is **deliberately not** in the key:

- Field confidence values. They legitimately change when a re-extraction runs;
  including them would split routing into a new row every time, defeating
  idempotency.
- Guardrail flags. Same reason.

What **is** in the key:

- `extraction_id` and `schema_name` — stable identity of the work item.
- `ROUTING_VERSION` — a constant in `backend/app/workflow.py`. Bumping it changes
  every key, which is what you want when the rule set itself changes (the M6 PR's
  decision log records the current value as `v1`). Bumping is **auditable** and
  triggers a fresh routing pass.

A test in `test_workflow.py` pins this contract: changing
`extraction_id`, `schema_name`, or `routing_version` changes the key; changing
confidence or flags does not.

## Persistence: `apply_routing`

```python
apply_routing(session, *, extraction_id, decision) -> WorkflowItem
```

Looks up the existing `workflow_items` row by `decision.idempotency_key` and:

- **Not found** — inserts a new row.
- **Found, same status** — no-op; returns the existing row.
- **Found, different status** — updates the row in place (one row per key, ever).
- **Found, status is `REJECTED` and new status is `AUTO_APPROVED`** — refuses with
  `IllegalTransition`. Promotion off rejection requires a human event, which is
  M7's audit-driven `POST /review/{id}/approve`.

Caller owns the transaction. The engine flushes but never commits.

### Demotions are allowed

`REJECTED` → `NEEDS_REVIEW` is allowed (e.g., a re-run that finds an extraction
was misjudged as a rejection). Only the `auto_approved` promotion is gated, because
that is the one transition with material impact (the row would silently flow to
production-as-truth).

## Replay protocol

```python
replay(session, *, extraction_id, settings=None) -> RoutingDecision
```

Reads the persisted `extractions` row (payload, per-field confidence, schema name)
and runs `route()` against it with `guardrail_flags=()`. Returns the recomputed
decision and writes nothing.

Two uses:

1. **Audit assertion (M7).** Given a `workflow_items` row, replay should produce
   the same status — modulo the audit trail of human decisions, which the M7
   replay test layers on top.
2. **Rule-version migration.** Bumping `ROUTING_VERSION` triggers a re-routing
   pass: call `replay` for every existing extraction; pass the new decision to
   `apply_routing`; observe per-row updates.

Replay does **not** carry guardrail flags, because they are a per-call signal, not
stored state. If you need flags during replay (e.g., to reconstruct an
`invalid_citation` rejection), record them on the audit event — that is M7.

`route_extraction(session, *, extraction_id, guardrail_flags=())` is a small
convenience that ties replay-style routing and idempotent persistence together for
callers (e.g., a worker that consumes new extractions, or the M9 eval harness).

## Invariants

The engine refuses to ship a decision that violates either of two invariants
(`_check_invariants`, called inside `route()`):

1. **`AUTO_APPROVED` requires every field at or above the threshold.** Returning
   `auto_approved` while at least one field is below the threshold is a rule bug
   and raises `AssertionError`.
2. **A rejecting guardrail flag MUST yield `REJECTED`.** Returning anything else
   while `invalid_citation` is present is a rule bug and raises `AssertionError`.

These run at decision time so a regression in `_decide_status` is caught
immediately rather than silently shipping a bad routing.

## Configuration

| Env var                       | Default | Description                                                       |
| ----------------------------- | ------- | ----------------------------------------------------------------- |
| `CONFIDENCE_REVIEW_THRESHOLD` | `0.75`  | Per-field cutoff used by the low-confidence rule.                 |

`ROUTING_VERSION` is a code-level constant (currently `"v1"`); bumping it is an
intentional, reviewable change, not a runtime knob.

## Test categories

`backend/tests/test_workflow.py` covers all four M6 DoD categories explicitly:

- **Determinism**: `route()` is a pure function of inputs; key recipe pinned.
- **Idempotency**: re-running `apply_routing` produces one DB row, verified at
  the SQL level.
- **Replay**: `replay()` reproduces decisions from storage, including low-confidence
  paths, and raises on unknown ids.
- **Invariants**: `_check_invariants` raises on the two illegal pairings;
  `route()` never returns `auto_approved` when any field is low.

Plus rule-precedence coverage (5 tests), transition-policy coverage (2 tests), and
`route_extraction` integration (2 tests).
