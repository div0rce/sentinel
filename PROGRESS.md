# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M0 — Scaffolding, tooling, CI
- **Status:** not started
- **Active branch:** _none_ (still on `main`; create `feat/m00-scaffold` to begin)
- **Last completed milestone:** _none_
- **`make check` passing:** n/a (project not scaffolded yet)
- **Last action:** repo created; brain files (`CLAUDE.md`, `MILESTONES.md`, `PROGRESS.md`, `HANDOFF.md`) added.
- **Next action:** run `/start-milestone 00`, scaffold per M0 scope, get CI green, open the M0 PR.
- **Blockers:** none.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☐ not started | — | |
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
