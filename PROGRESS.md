# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M4 — Structured extraction
- **Status:** in progress (started 2026-05-28)
- **Active branch:** `feat/m04-extraction`
- **Last completed milestone:** M3 — Retrieval + citation-grounded RAG (PR #4, merged 2026-05-28)
- **`make check` passing:** baseline green from M3 (76 tests); M4 work in progress
- **Last action:** ran `/start-milestone 04`, switched to `main`, fast-forwarded, created `feat/m04-extraction`.
- **Next action:** add Pydantic `ExtractedField[T]` wrapper + schema registry + `invoice` schema; build `extract.py` orchestrator with strict JSON parse + schema/citation validation + persistence or deterministic failure; add `POST /extract` router wired into `main.py`; add FakeLLM tests for valid extraction, malformed JSON, schema-invalid output, and bogus `source_chunk_id`.
- **Blockers:** none.

### M4 DoD checklist

- [ ] Extractions validate against the schema; each field carries confidence + source chunk id.
- [ ] Tests with FakeLLM fixtures cover valid extraction, malformed output handling, and persistence.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☑ merged | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ☑ merged | [#3](https://github.com/div0rce/sentinel/pull/3) | 2026-05-28 |
| M3 | Retrieval + RAG | `feat/m03-rag-query` | ☑ merged | [#4](https://github.com/div0rce/sentinel/pull/4) | 2026-05-28 |
| M4 | Structured extraction | `feat/m04-extraction` | ◐ in progress | — | started 2026-05-28 |
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
- 2026-05-28 (M2) — Stored chunk text must preserve byte/text provenance by slicing the original source string from `decode_with_offsets()` token spans. The chunker must not store lossy arbitrary token-window decodes.
- 2026-05-28 (M3) — Citation marker format is `[chunk:N]` where `N` is a chunk id. Cheap to parse with one regex, robust to source text, and unambiguous across milestones (M5 guardrails and M7 audit can reuse the same marker).
- 2026-05-28 (M3) — Citation-or-refuse refusal reasons are explicit strings: `empty_query`, `no_support`, `invalid_citation`, `uncited`. Surfacing the reason makes both the audit log (M7) and the eval harness (M9) able to bucket failures without re-running the pipeline.
- 2026-05-28 (M3) — Fabricated citation markers trigger refusal with `invalid_citation`; mixed valid+invalid citation outputs are rejected rather than silently dropping invalid ids while returning an answer.
- 2026-05-28 (M3) — `LLMClient.complete(system, user, max_tokens, temperature)` is single-turn by design. Streaming and tool use can extend the Protocol later without breaking the M3 RAG contract.
- 2026-05-28 (M3) — `llm_temperature` defaults to `0.0` per CLAUDE.md ("pin temperatures for LLM calls used in eval"). Production may raise it but must record the value alongside any reported metric.

---

## Mid-milestone scratch
> If you must stop mid-milestone, write down here exactly what is half-done and the precise next step,
> so the next session resumes in seconds. Clear this when the milestone merges.

- _(empty)_
