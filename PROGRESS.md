# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M5 — Guardrails
- **Status:** complete on branch (started 2026-05-28, completed 2026-05-28); awaiting CI green and human squash-merge
- **Active branch:** `feat/m05-guardrails` (PR open — see Milestone status)
- **Last completed milestone:** M4 — Structured extraction (PR #5, merged 2026-05-28)
- **`make check` passing:** yes locally on a freshly migrated DB (128 tests pass)
- **Last action:** committed 5 small Conventional Commits for M5 (guardrails module, wiring into ingest/rag/extract + extract response, docs/guardrails.md, unit + integration tests).
- **Next action:** human squash-merges the M5 PR. After merge, run `/start-milestone 06` to begin M6 (workflow engine).
- **Blockers:** none.

### M5 DoD verification

- [x] **PII patterns redacted before any LLM call and before storage (tested).**
  Two call sites apply `redact_pii` when `pii_redaction_enabled=True` (default):
  `ingest.ingest_document` redacts each chunk before `chunks_repo.bulk_insert`
  (pre-storage), and `rag._build_user_prompt` / `extract._build_user_prompt` redact
  question + chunk context before the LLM call (pre-LLM). Tests assert that a
  document containing email, phone, and SSN is stored with `[REDACTED:*]` markers,
  that the toggle disables the behaviour, that the document hash is keyed on the
  *original* text either way (re-ingest idempotency holds), and that the prompts
  observed by `FakeLLM` have PII replaced.
- [x] **Low-confidence extractions are flagged for review, never auto-applied
  (tested).** `extract_document` returns `requires_review` and
  `low_confidence_fields` populated from the guardrail helpers against
  `settings.confidence_review_threshold`. The flag is informational only —
  extractions still validate, persist, and return as before. Tests assert the flag
  is `True` exactly when at least one field is below threshold and that the field
  list is the offenders in insertion order.
- [x] **Guardrail behavior is config-driven and documented in `docs/`.**
  `PII_REDACTION_ENABLED` and `CONFIDENCE_REVIEW_THRESHOLD` are surfaced in
  `Settings`, `.env.example`, and `docs/guardrails.md` (patterns table, algorithm,
  wiring diagram, idempotency notes, tuning guidance, testing summary).

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☑ merged | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ☑ merged | [#3](https://github.com/div0rce/sentinel/pull/3) | 2026-05-28 |
| M3 | Retrieval + RAG | `feat/m03-rag-query` | ☑ merged | [#4](https://github.com/div0rce/sentinel/pull/4) | 2026-05-28 |
| M4 | Structured extraction | `feat/m04-extraction` | ☑ merged | [#5](https://github.com/div0rce/sentinel/pull/5) | 2026-05-28 |
| M5 | Guardrails | `feat/m05-guardrails` | ◐ complete on branch (PR open) | _filled in after `gh pr create`_ | 2026-05-28 |
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
- 2026-05-28 (M5) — PII redaction patterns are deterministic regexes ordered more-specific-first (EMAIL, SSN, CREDIT_CARD, PHONE, IPV4); replacement is `[REDACTED:KIND]`, chosen so the function is idempotent on a second pass. Defaults `PII_REDACTION_ENABLED=true`.
- 2026-05-28 (M5) — Pre-storage redaction is applied at ingest before `chunks_repo.bulk_insert`, but the document hash is computed on the *original* text. This keeps re-ingest idempotency intact across toggle flips: same content always hashes the same regardless of redaction state.
- 2026-05-28 (M5) — Pre-LLM redaction runs in both `rag._build_user_prompt` (question + chunks) and `extract._build_user_prompt` (chunk context). Defense in depth even when chunks were stored raw before M5 was wired up.
- 2026-05-28 (M5) — Confidence gating in M5 is **flag-only**. `ExtractionResult.requires_review` and `low_confidence_fields` are populated against `CONFIDENCE_REVIEW_THRESHOLD` (default 0.75) but the extraction is still validated, persisted, and returned. Routing happens in M6 / approval in M7; this milestone just labels.
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
