# PROGRESS.md — Sentinel live state

> **The single source of truth for "where am I."** Claude Code updates this at the end of every
> milestone (and before stopping mid-milestone). On resume, read this first, then verify against
> `git status`, `git log --oneline -10`, and `gh pr list`.

---

## Current state

- **Active milestone:** M7 — Immutable audit log + human-in-the-loop approval
- **Status:** in progress (started 2026-05-29)
- **Active branch:** `feat/m07-audit-hitl`
- **Last completed milestone:** M6 — Workflow engine (PR #7, merged 2026-05-29)
- **`make check` passing:** baseline green from M6 (150 tests); M7 work in progress
- **Last action:** ran `/start-milestone 07`, switched to `main`, fast-forwarded, created `feat/m07-audit-hitl`.
- **Next action:** add `backend/app/audit.py` semantic emitters (`emit_extraction_created`, `emit_workflow_routed`, `emit_review_decision`, `replay_workflow_state`); wire emission into `extract.extract_document` and `workflow.route_extraction` (only on actual state change); add `backend/app/routers/review.py` with `GET /review` queue and `POST /review/{id}/approve|reject` (human event bypasses `apply_routing`'s `IllegalTransition` guard); add the state-from-replay test; document in `docs/audit-and-review.md`.
- **Blockers:** none.

### M7 DoD checklist

- [ ] Every model suggestion and human decision writes exactly one audit event (tested).
- [ ] Approve/reject transitions are valid and audited.
- [ ] **State-from-replay test:** current `workflow_items` state is reconstructable from `audit_events`.

---

## Milestone status

| # | Milestone | Branch | Status | PR | Notes |
|---|-----------|--------|--------|----|-------|
| M0 | Scaffolding, tooling, CI | `feat/m00-scaffold` | ☑ merged | [#1](https://github.com/div0rce/sentinel/pull/1) | 2026-05-28 |
| M1 | Data model + migrations | `feat/m01-data-model` | ☑ merged | [#2](https://github.com/div0rce/sentinel/pull/2) | 2026-05-28 |
| M2 | Ingestion + embeddings | `feat/m02-ingestion` | ☑ merged | [#3](https://github.com/div0rce/sentinel/pull/3) | 2026-05-28 |
| M3 | Retrieval + RAG | `feat/m03-rag-query` | ☑ merged | [#4](https://github.com/div0rce/sentinel/pull/4) | 2026-05-28 |
| M4 | Structured extraction | `feat/m04-extraction` | ☑ merged | [#5](https://github.com/div0rce/sentinel/pull/5) | 2026-05-28 |
| M5 | Guardrails | `feat/m05-guardrails` | ☑ merged | [#6](https://github.com/div0rce/sentinel/pull/6) | 2026-05-29 |
| M6 | Workflow engine | `feat/m06-workflow-engine` | ☑ merged | [#7](https://github.com/div0rce/sentinel/pull/7) | 2026-05-29 |
| M7 | Audit log + HITL | `feat/m07-audit-hitl` | ◐ in progress | — | started 2026-05-29 |
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
- 2026-05-29 (M6) — Workflow rules are pure: `route(RoutingInputs) -> RoutingDecision` is a function with no I/O. Same inputs always produce the same decision. Persistence (`apply_routing`) and replay (`replay`) live in the same module but call only this pure core.
- 2026-05-29 (M6) — Idempotency-key recipe is `sha256(f"{extraction_id}|{schema_name}|{routing_version}")`. Confidence and guardrail flags are intentionally NOT in the key — they legitimately change between routing calls, and including them would break re-run idempotency. `ROUTING_VERSION` (currently `"v1"`) is a code-level constant; bumping it triggers re-routing of every previously routed extraction.
- 2026-05-29 (M6) — Rule precedence (top-down): `invalid_citation` flag → `rejected`; any field below threshold → `needs_review`; any other guardrail flag → `needs_review`; otherwise → `auto_approved`. Rejection is terminal at routing time (rule 1 beats rule 2). The two invariants `_check_invariants` enforces are pinned by tests so a rule regression fails loudly.
- 2026-05-29 (M6) — `apply_routing` allows `REJECTED → NEEDS_REVIEW` demotion but refuses `REJECTED → AUTO_APPROVED` promotion with `IllegalTransition`. Promotion off rejection requires a human event; that path arrives with M7's `POST /review/{id}/approve`.
- 2026-05-29 (M6) — Workflow idempotent persistence uses a PostgreSQL `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` path, so concurrent workers racing after a stale read converge on the same row without surfacing `IntegrityError`.
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
