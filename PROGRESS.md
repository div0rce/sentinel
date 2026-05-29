# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M4 — Structured extraction
- **Status:** complete on branch (started 2026-05-28, completed 2026-05-28); invoice date validation fix applied and awaiting CI green + human squash-merge
- **Active branch:** `feat/m04-extraction` (PR open — see Milestone status)
- **Last completed milestone:** M3 — Retrieval + citation-grounded RAG (PR #4, merged 2026-05-28)
- **`make check` passing:** yes locally on a freshly migrated DB (99 tests pass)
- **Last action:** fixed PR review finding: invoice `issue_date` is now constrained to real `YYYY-MM-DD` ISO date strings in validation and generated JSON Schema; verified focused extraction tests.
- **Next action:** human squash-merges the M4 PR. After merge, run `/start-milestone 05` to begin M5 (guardrails).
- **Blockers:** none.

### M4 DoD verification

- [x] **Extractions validate against the schema; each field carries confidence + source chunk id.**
  Every field in every registered schema is wrapped in `ExtractedField[T]` (Pydantic v2,
  `extra='forbid'`, `confidence ∈ [0,1]`, `source_chunk_id ≥ 1`). The orchestrator
  validates the LLM output against the registered schema and additionally verifies that
  every `source_chunk_id` is in the supplied chunk set; fabricated ids are a hard
  failure (`reason='invalid_citation'`). On success, the orchestrator unwraps the
  validated model into three flat dicts (`payload`, `field_confidence`, `field_citations`)
  before persisting.
- [x] **Tests with FakeLLM fixtures cover valid extraction, malformed output handling, and
  persistence.** 23 new M4 tests:
  - **valid**: round-trip produces an extraction row whose payload, per-field confidence,
    and per-field citations are recoverable from the repo; `model_name='fake-llm'` captured.
  - **malformed**: `parse_error` on non-JSON, `parse_error` on JSON-but-not-an-object,
    `schema_invalid` on missing required fields / out-of-range confidence / extra
    forbidden keys / invalid invoice issue-date shape, `invalid_citation` on a fabricated `source_chunk_id`,
    `document_not_found` on unknown ids, `no_chunks` on empty docs, `unknown_schema` on
    unregistered names.
  - **persistence**: parametrized test verifies failures (parse_error, schema_invalid)
    do NOT add an extraction row; only `status='ok'` writes.
  - **router**: 422 validation, 200 happy path with full response shape, 200 with
    `status='failed'` and a typed reason on every failure mode.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☑ merged | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ☑ merged | [#3](https://github.com/div0rce/sentinel/pull/3) | 2026-05-28 |
| M3 | Retrieval + RAG | `feat/m03-rag-query` | ☑ merged | [#4](https://github.com/div0rce/sentinel/pull/4) | 2026-05-28 |
| M4 | Structured extraction | `feat/m04-extraction` | ◐ complete on branch (PR open) | _filled in after `gh pr create`_ | 2026-05-28 |
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
- 2026-05-28 (M4) — Every extraction-schema field is wrapped in `ExtractedField[T]` (PEP 695 generic Pydantic v2 model, `extra='forbid'`). Confidence + source chunk id are not optional add-ons; the LLM is required to emit them per field, and Pydantic validation rejects anything missing them. Avoids the "we'll add provenance later" trap.
- 2026-05-28 (M4) — Schemas are registered in a flat `name → class` dict (`extraction_schemas/registry.py`). Adding a schema is a two-line edit; the orchestrator and `POST /extract` resolve by string name. M4 ships one schema (`invoice`); the M9 eval harness can extend the registry.
- 2026-05-28 (M4) — Extraction failures (`parse_error`, `schema_invalid`, `invalid_citation`, `document_not_found`, `no_chunks`, `unknown_schema`) **never persist** an `extractions` row. Surfacing the typed reason to the caller is enough for M5 guardrails / M7 audit / M9 eval to bucket failures without polluting the success-only table.
- 2026-05-28 (M4) — Citation validation reuses the M3 posture: a `source_chunk_id` not in the supplied chunk set is a hard failure (`invalid_citation`), not a silent drop. Same invariant the M3 RAG layer enforces with `[chunk:N]` markers.
- 2026-05-28 (M4) — Invoice `issue_date` remains persisted as a string but is schema-constrained to a real ISO `YYYY-MM-DD` date; non-ISO or impossible dates fail schema validation before persistence.

---

## Mid-milestone scratch
> If you must stop mid-milestone, write down here exactly what is half-done and the precise next step,
> so the next session resumes in seconds. Clear this when the milestone merges.

- _(empty)_
