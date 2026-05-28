# MILESTONES.md — Sentinel build plan

Sequential, dependency-ordered. **Build them in order.** Each milestone is one feature branch and one
squash-merge PR. After M9 you have real evaluation numbers for the résumé; M10–M11 make it deployable
and presentable. Do not skip ahead — later milestones assume earlier ones exist.

**Conventions**
- Branch: `feat/mNN-slug`
- PR title becomes the single squashed commit on `main` (so it must read cleanly).
- DoD = Definition of Done. A milestone is complete only when **all** boxes are satisfiable, `make check`
  passes, and `PROGRESS.md` is updated.

---

## M0 — Scaffolding, tooling, CI
- **Branch:** `feat/m00-scaffold` · **PR title:** `chore: scaffold project, tooling, and CI`
- **Goal:** An empty but professional repo that boots, lints, type-checks, tests, and runs CI green.
- **Scope:**
  - `pyproject.toml` (uv), `Makefile`, `.gitignore`, `.env.example`, `.editorconfig`.
  - `ruff` + `mypy` + `pytest` configured. `pre-commit` with `no-commit-to-branch`, `ruff`, `ruff-format`,
    `detect-private-key`, `check-merge-conflict`, `end-of-file-fixer`, `trailing-whitespace`.
  - `docker-compose.yml` for Postgres 16 + pgvector (dev).
  - Minimal FastAPI app with `GET /health`. One trivial passing test.
  - `.claude/commands/{resume,start-milestone,finish-milestone,review}.md` and `.claude/settings.json`
    (copy from `HANDOFF.md` appendix).
  - `.github/workflows/ci.yml` and `.github/pull_request_template.md`.
  - `docs/` skeleton + `docs/adr/0001-record-architecture-decisions.md`.
  - `data/sample/README.md` stating all data is synthetic.
- **DoD:**
  - [ ] `make dev` serves `/health` returning `{"status":"ok"}`.
  - [ ] `make check` passes locally; CI passes on the PR.
  - [ ] `no-commit-to-branch` actually blocks a commit on `main` (verify once).
  - [ ] Repo tree matches `CLAUDE.md` "Target layout".

## M1 — Data model + migrations
- **Branch:** `feat/m01-data-model` · **PR title:** `feat: data model and migrations`
- **Goal:** Persistent schema with pgvector, applied via Alembic.
- **Scope:** SQLAlchemy 2.x models — `documents`, `chunks` (with `vector` column), `extractions`,
  `workflow_items`, `audit_events` (append-only). `config.py` (pydantic-settings), `db.py` (engine/session).
  Alembic migration enabling the `vector` extension and creating tables. Repository helpers.
- **DoD:**
  - [ ] `make migrate` applies cleanly on a fresh DB; pgvector extension enabled.
  - [ ] Models + repositories unit-tested against the CI Postgres service.
  - [ ] `audit_events` has no update/delete path in the repository layer.

## M2 — Ingestion + embedding pipeline
- **Branch:** `feat/m02-ingestion` · **PR title:** `feat: document ingestion and embedding pipeline`
- **Goal:** Load a corpus → chunk → embed → store vectors, idempotently.
- **Scope:** `embeddings/` interface + one hosted provider + deterministic `FakeEmbedder` for tests.
  Token-based chunking with overlap. `ingest.py` pipeline keyed by document hash (re-ingest = no dupes).
  Synthetic corpus generator script → `data/sample/`. `make seed`.
- **DoD:**
  - [ ] `make seed` ingests the synthetic corpus; `chunks` populated with embeddings.
  - [ ] Tests: chunking is deterministic; re-ingesting the same document creates no duplicates.
  - [ ] No live embedding calls in CI (FakeEmbedder used).

## M3 — Retrieval + citation-grounded RAG
- **Branch:** `feat/m03-rag-query` · **PR title:** `feat: retrieval and citation-grounded RAG query`
- **Goal:** Ask a question, get an answer with citations — or a refusal.
- **Scope:** pgvector cosine top-k retrieval. `llm/` interface + Claude client + `FakeLLM` for tests.
  `rag.py`: retrieve → prompt → answer with inline citations mapped to `chunk` ids. **Citation-or-refuse**:
  if top score < threshold or no support, refuse. `POST /query` router + response schema.
- **DoD:**
  - [ ] `POST /query` returns answer + citations for an in-corpus question (manual check with real key).
  - [ ] Tests (FakeLLM): retrieval ordering, refusal when unsupported, citation→chunk mapping correctness.

## M4 — Structured extraction
- **Branch:** `feat/m04-extraction` · **PR title:** `feat: schema-constrained structured extraction`
- **Goal:** Turn documents into structured records with confidence + provenance.
- **Scope:** `extract.py`: LLM extraction constrained to a Pydantic JSON schema; capture **per-field
  confidence** and **source citation** per field; persist to `extractions`. `POST /extract`.
- **DoD:**
  - [ ] Extractions validate against the schema; each field carries confidence + source chunk id.
  - [ ] Tests with FakeLLM fixtures cover valid extraction, malformed output handling, and persistence.

## M5 — Guardrails
- **Branch:** `feat/m05-guardrails` · **PR title:** `feat: guardrails (PII redaction, confidence gating, refusal)`
- **Goal:** Centralized, deterministic safety layer.
- **Scope:** `guardrails.py`: deterministic PII redaction (regex set; document patterns covered) applied
  pre-LLM and pre-storage; confidence-gating thresholds (config-driven); centralized citation-or-refuse.
  Wire into M3/M4 paths.
- **DoD:**
  - [ ] PII patterns redacted before any LLM call and before storage (tested).
  - [ ] Low-confidence extractions are flagged for review, never auto-applied (tested).
  - [ ] Guardrail behavior is config-driven and documented in `docs/`.

## M6 — Deterministic, idempotent workflow engine
- **Branch:** `feat/m06-workflow-engine` · **PR title:** `feat: deterministic idempotent workflow engine`
- **Goal:** The differentiator. Route records by rules, deterministically and replayably.
- **Scope:** `workflow.py`: pure rules mapping (extraction + confidence + guardrail flags) →
  `workflow_items.status` (`auto_approved` / `needs_review` / `rejected`). Idempotency keys; replay support;
  runtime invariant checks. No hidden state; same inputs → same outputs.
- **DoD:**
  - [ ] **Determinism test:** identical inputs → identical routing across runs.
  - [ ] **Idempotency test:** re-running routing produces no duplicate items / side effects.
  - [ ] **Replay test:** routing can be recomputed from stored inputs.
  - [ ] Invariants enforced and tested (e.g., a rejected item never becomes auto-approved without an event).

## M7 — Immutable audit log + human-in-the-loop approval
- **Branch:** `feat/m07-audit-hitl` · **PR title:** `feat: immutable audit log and human-in-the-loop approval`
- **Goal:** Every suggestion and decision is recorded; humans approve/reject the queue.
- **Scope:** `audit.py`: append-only events (`actor`, `action`, `before`, `after`, `request_id`, `ts`).
  Routers: `GET /review` (queue), `POST /review/{id}/approve|reject` (writes decision + audit event).
  Emit audit events for model suggestions (M3/M4) and human decisions.
- **DoD:**
  - [ ] Every model suggestion and human decision writes exactly one audit event (tested).
  - [ ] Approve/reject transitions are valid and audited.
  - [ ] **State-from-replay test:** current `workflow_items` state is reconstructable from `audit_events`.

## M8 — Frontend (dashboard + query + review)
- **Branch:** `feat/m08-frontend` · **PR title:** `feat: React dashboard, query, and review UI`
- **Goal:** A usable UI over the API. Clean, not flashy.
- **Scope:** Vite + React + TS. Views: **Query** (ask + cited answers), **Review** (approve/reject queue),
  **Dashboard** (Recharts: volume over time, category breakdown, confidence distribution, SLA-risk).
  Typed API client. Loading/empty/error states.
- **DoD:**
  - [ ] All three views work against the running backend.
  - [ ] Dashboard renders the four KPI visuals from real API data.
  - [ ] At least a smoke/component test for the query and review flows.

## M9 — Evaluation harness (produces résumé metrics)
- **Branch:** `feat/m09-eval` · **PR title:** `feat: evaluation harness and benchmark results`
- **Goal:** Reproducible, defensible numbers. **These are the figures for the résumé.**
- **Scope:** `eval/`: hand-labeled synthetic benchmark (ground-truth fields + relevance judgments).
  Scripts computing **field-level extraction accuracy**, **retrieval precision@k**, and an
  **answer-faithfulness / citation-validity** check. `make eval` writes `eval/RESULTS.md` (methodology +
  numbers + dataset size + date). Tests for the eval scripts themselves.
- **DoD:**
  - [ ] `make eval` runs end-to-end and writes `eval/RESULTS.md` with metrics, k, dataset size, and method.
  - [ ] Methodology is documented well enough to defend verbally in an interview.
  - [ ] Numbers are real (from this run). Record them in `PROGRESS.md` "Decision log" too.

## M10 — Containerization, Terraform (AWS), CD
- **Branch:** `feat/m10-deploy` · **PR title:** `feat: containerization, Terraform (AWS), and CD pipeline`
- **Goal:** Deployable to cloud with infra-as-code, cost-controlled.
- **Scope:** Production Dockerfiles (backend, frontend). Terraform in `infra/`: ECR, ECS Fargate service,
  RDS Postgres, networking, security groups (modular). GitHub Actions CD: build → push to ECR → deploy,
  **gated behind `workflow_dispatch`** (manual) to control cost. Structured logging (`structlog`),
  request IDs, `/health`. Secrets via SSM / GitHub secrets.
- **DoD:**
  - [ ] `terraform plan` is clean; `apply` provisions the stack (tear down after demo to avoid charges).
  - [ ] CD workflow builds and deploys on manual dispatch.
  - [ ] App is reachable at a URL (capture screenshots before teardown).

## M11 — Docs, architecture diagram, demo
- **Branch:** `feat/m11-docs-demo` · **PR title:** `docs: README, architecture diagram, and demo`
- **Goal:** Portfolio-ready. A reviewer can understand and run it in minutes.
- **Scope:** Final `README.md` (problem → architecture → features → quickstart → eval results → governance →
  **limitations + synthetic-data disclaimer** → roadmap → license). `docs/architecture.md` with a Mermaid
  diagram exported to `docs/architecture.png`. `docs/demo.md` script (the 7-step demo). CI badge. License.
- **DoD:**
  - [ ] README is complete and accurate; quickstart works from a clean clone.
  - [ ] Architecture diagram committed (source + image).
  - [ ] Limitations + synthetic-data disclaimer present and honest.

---

## Backlog (only after M11, optional)
- Multi-tenant separation; role-based access on the review queue.
- Eval expansion (larger labeled set, per-category breakdown).
- Observability: OpenTelemetry traces, dashboards.
- Reranking stage before generation.

> Do not pull backlog items into earlier PRs. Park ideas here.
