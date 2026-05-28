# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M1 — Data model + migrations
- **Status:** complete on branch (started 2026-05-28, completed 2026-05-28); Codex review fixes applied and awaiting CI green + human squash-merge
- **Active branch:** `feat/m01-data-model` (PR open — see Milestone status)
- **Last completed milestone:** M0 — Scaffolding, tooling, CI (PR #1, merged 2026-05-28)
- **`make check` passing:** yes locally (ruff + ruff-format + mypy strict on 22 files + 31 pytest tests)
- **Last action:** fixed PR #2 review findings: ORM vector dimension is schema-owned and audit read helpers now return immutable DTOs; verified with `make check`, `make migrate`, and `alembic check`.
- **Next action:** human squash-merges the M1 PR. After merge, run `/start-milestone 02` to begin M2 (ingestion + embeddings).
- **Blockers:** none.

### M1 DoD verification

- [x] **`make migrate` applies cleanly on a fresh DB; pgvector extension enabled.** Verified locally
  against Postgres.app (pgvector 0.8.1) on a dedicated `sentinel_m1_local` DB: `alembic upgrade head`
  is clean, idempotent, and fully reversible (`downgrade base` drops tables, enum, *and* extension;
  re-`upgrade head` restores everything). CI re-verifies on every PR via an explicit
  `uv run alembic upgrade head` step against the pgvector/pgvector:pg16 service container.
- [x] **Models + repositories unit-tested against the CI Postgres service.** 31 tests cover schema
  introspection, model round-trips, FK/unique constraints, JSONB round-trip on extractions and
  audit_events, every public repo function, ORM vector metadata invariants, and behaviour of the
  audit-events append/read helpers.
- [x] **`audit_events` has no update/delete path in the repository layer.** Enforced two ways:
  (1) the module exposes only `append` and read functions; (2) an introspection test fails if any
  future change adds a public symbol matching forbidden mutator names or prefixes
  (`update*`, `delete*`, `remove*`, `set*`, etc.). Read helpers return immutable `AuditEventRead`
  DTOs rather than session-tracked ORM rows.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ◐ complete on branch (PR open) | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ☐ | — | |
| M3 | Retrieval + RAG | `feat/m03-rag-query` | ☐ | — | |
| M4 | Structured extraction | `feat/m04-extraction` | ☐ | — | |
| M5 | Guardrails | `feat/m05-guardrails` | ☐ | — | |
| M6 | Workflow engine | `feat/m06-workflow-engine` | ☐ | — | |
| M7 | Audit log + HITL | `feat/m07-audit-hitl` | ☐ | — | |
| M8 | Frontend | `feat/m08-frontend` | ☐ | — | |
| M9 | Evaluation harness | `feat/m09-eval` | ☐ | — | |
| M10 | Deploy (Docker/Terraform/CD) | `feat/m10-deploy` | ☐ | — | |
| M11 | Docs + diagram + demo | `feat/m11-docs-demo` | ☐ | — | |

Status key: ☐ not started · ◐ in progress · ☑ merged

---

## Decision log
> One line per real decision (architecture choices, library picks, thresholds, **measured eval numbers**).
> Add an ADR under `docs/adr/` for anything architectural.

- 2026-05-28 (M1) — Database vector dimension is canonical at `vector(1536)` via `SCHEMA_EMBEDDING_DIM`, matching the initial migration. Runtime embedding config must match the schema or be validated before insertion in M2; schema dimension changes require a migration.
- 2026-05-28 (M1) — `WorkflowItem.status` persisted as the enum *value* (`needs_review`), not the Python *name* (`NEEDS_REVIEW`), via `SAEnum(values_callable=...)`; matches the SQL enum the migration creates and keeps audit JSONB readable.
- 2026-05-28 (M1) — Repository layer is functional (one module per aggregate, plain functions taking an active `Session`); transaction boundaries are owned by the caller (FastAPI dep, ingestion pipeline). `audit_events` exposes only `append` and read helpers; an introspection test fails on any future mutator.
- 2026-05-28 (M1) — `audit_events.append()` may return the newly inserted ORM row for write flow, but read helpers return immutable detached `AuditEventRead` DTOs so callers cannot mutate or delete audit rows through repository reads.

---

## Mid-milestone scratch
> If you must stop mid-milestone, write down here exactly what is half-done and the precise next step,
> so the next session resumes in seconds. Clear this when the milestone merges.

- _(empty)_
