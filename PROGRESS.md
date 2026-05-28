# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M1 — Data model + migrations
- **Status:** in progress (started 2026-05-28)
- **Active branch:** `feat/m01-data-model`
- **Last completed milestone:** M0 — Scaffolding, tooling, CI (PR #1, merged 2026-05-28)
- **`make check` passing:** baseline green from M0; M1 work in progress
- **Last action:** ran `/start-milestone 01`, switched to `main`, fast-forwarded, created `feat/m01-data-model`.
- **Next action:** add SA 2.x + pgvector + Alembic + pydantic-settings deps; scaffold `config.py`, `db.py`, `models.py`, Alembic env + initial migration, repositories, tests.
- **Blockers:** none.

### M1 DoD checklist

- [ ] `make migrate` applies cleanly on a fresh DB; pgvector extension enabled.
- [ ] Models + repositories unit-tested against the CI Postgres service.
- [ ] `audit_events` has no update/delete path in the repository layer.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ◐ in progress | — | started 2026-05-28 |
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

- _(none yet)_

---

## Mid-milestone scratch
> If you must stop mid-milestone, write down here exactly what is half-done and the precise next step,
> so the next session resumes in seconds. Clear this when the milestone merges.

- _(empty)_
