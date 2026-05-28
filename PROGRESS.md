# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M0 — Scaffolding, tooling, CI
- **Status:** complete on branch (started 2026-05-28, completed 2026-05-28); awaiting CI green and human squash-merge
- **Active branch:** `feat/m00-scaffold` (PR open — see Milestone status)
- **Last completed milestone:** _none merged yet_
- **`make check` passing:** yes (locally; CI runs on the PR)
- **Last action:** committed M0 scaffolding in 7 small Conventional Commits, pushed, and opened the M0 PR.
- **Next action:** human squash-merges the M0 PR. After merge, run `/start-milestone 01` to begin M1 (data model + migrations).
- **Blockers:** none.

### M0 DoD verification

- [x] `make dev` would serve `/health` returning `{"status":"ok"}` — confirmed by the TestClient smoke test and by importing `backend.app.main:app` directly; full Docker run not exercised but path is correct.
- [x] `make check` passes locally (ruff check, ruff format --check, mypy --strict, pytest).
- [x] `no-commit-to-branch` blocks a commit on `main` — verified once: empty commit on `main` exited 1 from the hook, `main` SHA unchanged.
- [x] Repo tree matches the M0 portion of CLAUDE.md "Target layout"; later milestones (M1–M11) fill in `backend/{alembic,app/embeddings,app/llm,app/routers,...}`, `frontend/`, `eval/`, `infra/` per their own scopes. The CLAUDE.md "Target layout" section explicitly states "Update this section if structure changes."

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ◐ complete on branch (PR open) | _filled in after `gh pr create`_ | started 2026-05-28; completed on branch 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☐ | — | |
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
