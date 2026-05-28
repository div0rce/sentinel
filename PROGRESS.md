# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M2 — Ingestion + embedding pipeline
- **Status:** complete on branch (started 2026-05-28, completed 2026-05-28); awaiting CI green and human squash-merge
- **Active branch:** `feat/m02-ingestion` (PR open — see Milestone status)
- **Last completed milestone:** M1 — Data model + migrations (PR #2, merged 2026-05-28)
- **`make check` passing:** yes locally on a freshly migrated DB (32 source files mypy-clean, 56 tests pass)
- **Last action:** committed 9 small Conventional Commits covering deps, settings, embeddings, chunking, ingest pipeline + CLI, synthetic corpus + generator, tests, and CI; verified `make seed` end-to-end against Postgres.app (15 docs ingested with embeddings, re-run reports 15 skipped).
- **Next action:** human squash-merges the M2 PR. After merge, run `/start-milestone 03` to begin M3 (retrieval + RAG).
- **Blockers:** none.

### M2 DoD verification

- [x] **`make seed` ingests the synthetic corpus; `chunks` populated with embeddings.** Verified
  locally against Postgres.app on a dedicated `sentinel_m2_local` DB: 15 documents ingested (the
  14 deterministic synthetic markdown files plus the corpus README), 15 chunks all with non-null
  `vector(1536)` embeddings produced by `FakeEmbedder`. Re-running `make seed` reports
  `ingested=0 skipped=15` (idempotency). CI re-verifies on every PR.
- [x] **Chunking is deterministic; re-ingesting the same document creates no duplicates.** Tests:
  `test_chunking_is_deterministic_across_runs`, plus an overlap=0 invariant
  (`sum(token_count) == len(encoder.encode(text))`); `test_re_ingesting_same_content_is_a_no_op`
  asserts the second `ingest_document` returns `status='skipped'` even from a different source path
  and adds zero new chunk rows.
- [x] **No live embedding calls in CI (FakeEmbedder used).** Job-level `EMBEDDINGS_PROVIDER=fake`
  in `.github/workflows/ci.yml` plus tests' `Settings(embeddings_provider="fake")` calls. The
  `OpenAIEmbedder` still exists for production but no test path constructs one with a real key.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☑ merged | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ◐ complete on branch (PR open) | _filled in after `gh pr create`_ | 2026-05-28 |
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
- 2026-05-28 (M2) — Chunker is pinned to tiktoken's `cl100k_base` encoder so chunk boundaries align with `text-embedding-3-*` (the planned production embedder). Switching providers later will require either re-chunking or accepting that boundaries no longer align with the new tokenizer.
- 2026-05-28 (M2) — `FakeEmbedder` produces deterministic SHA-256-stretched, L2-normalized vectors of `SCHEMA_EMBEDDING_DIM` length. CI runs offline with `EMBEDDINGS_PROVIDER=fake`, satisfying the "no live API calls in CI" constraint without skipping the embedding code path.
- 2026-05-28 (M2) — Ingestion idempotency is keyed on `sha256(canonical_text)`. Whitespace is **not** normalized: a single character difference (including trailing newline) makes two distinct documents. This avoids the "is it the same?" ambiguity but means callers must canonicalize upstream if they want fuzzy idempotency.
- 2026-05-28 (M2) — `OpenAIEmbedder` uses `httpx` directly rather than the OpenAI SDK; the embeddings endpoint is small and stable, and avoiding the SDK saves a transitive dependency. CI does not exercise this provider.

---

## Mid-milestone scratch
> If you must stop mid-milestone, write down here exactly what is half-done and the precise next step,
> so the next session resumes in seconds. Clear this when the milestone merges.

- _(empty)_
