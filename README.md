# Sentinel — governed document intelligence

[![CI](https://github.com/div0rce/sentinel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/div0rce/sentinel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Sentinel is a portfolio-grade implementation of an **enterprise RAG + structured
extraction platform with deterministic, auditable governance**. It turns an
unstructured document corpus into two outputs:

1. **Source-cited natural-language answers** (citation-or-refuse).
2. **Schema-structured records with per-field confidence and provenance**.

Both outputs run through a deterministic, idempotent, **human-in-the-loop**
workflow with an **append-only audit log**. The full pipeline — ingestion,
retrieval, RAG, extraction, guardrails, workflow engine, audit — is
exercised end-to-end against a hand-labeled synthetic benchmark by an
evaluation harness that **refuses to fabricate metric values** when the
fakes are in play.

> All sample data and benchmark labels are synthetic. The system has never
> seen real customer data and is not intended for production use as-is.
> See [Limitations & synthetic-data disclaimer](#limitations--synthetic-data-disclaimer).

---

## Table of contents

- [Problem](#problem)
- [Architecture](#architecture)
- [Features](#features)
- [Quickstart](#quickstart)
- [Evaluation](#evaluation)
- [Governance & guardrails](#governance--guardrails)
- [Deployment](#deployment)
- [Limitations & synthetic-data disclaimer](#limitations--synthetic-data-disclaimer)
- [Roadmap](#roadmap)
- [Project map](#project-map)
- [License](#license)

---

## Problem

Most enterprise RAG demos answer the question "can an LLM look something up
in our docs?" Most enterprise extraction demos answer "can an LLM populate a
JSON schema?" Both questions are easy. The hard questions are operational:

- How do you know the answer is **grounded** in the corpus, not hallucinated?
- How do you know which **fields are reliable** and which need a human?
- How do you **route** ambiguous output to a reviewer and **prove**, after
  the fact, who decided what and why?
- How do you **measure** the system's quality on a labeled benchmark — without
  fabricating numbers when the LLM isn't actually wired up?
- How do you ship the whole thing as a **container that runs on AWS** with a
  **non-publicly-accessible database**, **no long-lived CI keys**, and a
  **manual-only** deployment trigger so the bill stays bounded?

Sentinel is one opinionated answer to all of those. The architecture is built
around a small set of deterministic invariants that are tested in code:

- **Citation-or-refuse.** Every answer is supported by a retrieved chunk; if
  not, the system refuses *before* calling the LLM. The same rule applies
  field-by-field to extraction.
- **Append-only audit.** Every model suggestion and every human decision
  writes one row to `audit_events`. The repository layer has no update or
  delete path. Reconstructing any workflow item's state by replay is a
  tested property.
- **Idempotent, deterministic workflow.** Routing or re-routing the same
  extraction never creates a second `workflow_items` row. Same input → same
  state.
- **PII redaction is pre-LLM and pre-storage.** The LLM never sees raw
  emails / phone numbers / SSNs / credit cards / IPs; the database never
  stores them in chunk text.
- **Honesty discipline.** The eval harness emits `n/a (...)` rather than a
  fabricated number when a fake provider is in play. `eval/RESULTS.md` ships
  in a methodology-only state until a real-provider run produces real
  numbers.

## Architecture

![Sentinel architecture](docs/architecture.png)

Headline shape: **Frontend (Vite + React + TypeScript)** behind nginx →
**Backend (FastAPI on Python 3.12)** with a small set of pipeline modules
(`retrieval`, `rag`, `extract`, `workflow`) and cross-cutting governance
(`guardrails`, `audit`) → **Postgres 16 + pgvector** → **external LLM and
embedding providers** (Anthropic Claude, OpenAI embeddings — both behind
narrow interfaces and mocked in tests).

The full architectural cross-reference, including end-to-end sequence
diagrams for `/query`, `/extract`, and human review, an ER diagram, and the
M10 deployment topology, is in [`docs/architecture.md`](docs/architecture.md).
The diagram source is [`docs/architecture.mmd`](docs/architecture.mmd) — render
with `npx -y --package=@mermaid-js/mermaid-cli mmdc -i docs/architecture.mmd -o docs/architecture.png --backgroundColor white --width 1600 --scale 2`.

## Features

| Capability | Where it lives | Tested by |
| --- | --- | --- |
| Idempotent ingestion + chunking + embedding | `backend/app/ingest.py`, `backend/app/embeddings/` | `test_ingest.py`, `test_chunking.py` |
| pgvector cosine top-k retrieval | `backend/app/retrieval.py` | `test_retrieval.py` |
| Citation-grounded RAG (`POST /query`) | `backend/app/rag.py`, `backend/app/routers/query.py` | `test_rag.py`, `test_query_router.py` |
| Schema-constrained structured extraction (`POST /extract`) | `backend/app/extract.py`, `backend/app/extraction_schemas/` | `test_extract.py`, `test_extract_router.py` |
| PII redaction + confidence gating | `backend/app/guardrails.py` | `test_guardrails.py` |
| Deterministic, idempotent workflow FSM | `backend/app/workflow.py` | `test_workflow.py` |
| Append-only audit log + replay | `backend/app/audit.py` | `test_audit_events_append_only.py` |
| Human-in-the-loop review API + UI | `backend/app/routers/review.py`, `frontend/src/views/Review.tsx` | `test_audit_and_review.py`, `Review.test.tsx` |
| KPI dashboard (volume, categories, confidence, SLA) | `backend/app/routers/dashboard.py`, `frontend/src/views/Dashboard.tsx` | `test_dashboard.py` |
| Structured logging + request-id correlation | `backend/app/observability.py` | `test_request_id.py` |
| Eval harness (extraction / retrieval / RAG) | `eval/` | `test_eval_harness.py` |
| Containerized + Terraform demo deploy on AWS | `backend/Dockerfile`, `frontend/Dockerfile`, `infra/` | `terraform fmt+validate` in CI |
| Manual-dispatch CD via GitHub OIDC | `.github/workflows/cd.yml`, `infra/modules/ci_oidc/` | review-tested |


## Quickstart

The full step-by-step is in [`docs/demo.md`](docs/demo.md). Short version
(developer laptop, ~15 minutes):

```bash
# 1. clone
git clone https://github.com/div0rce/sentinel.git
cd sentinel
cp .env.example .env   # set ANTHROPIC_API_KEY and OPENAI_API_KEY

# 2. start Postgres + the API
docker compose up -d db
make dev                       # uvicorn on :8000

# 3. start the frontend (second terminal)
cd frontend && npm ci && npm run dev   # Vite on :5173

# 4. migrate + seed the synthetic corpus
make migrate
make seed

# 5. ask a question against the synthetic corpus
curl -s http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the total amount due on the Initech Components invoice issued on 2026-01-22?"}' | jq
```

Open <http://localhost:5173> for the SPA: **Query**, **Review**, and
**Dashboard** views.

### Run the test suite

```bash
make check        # ruff + mypy + 195 backend pytest + 7 frontend Vitest
```

CI runs the same matrix plus `terraform fmt -check && terraform validate`
on every PR. None of these steps require API keys; the `fake` LLM and
embedder run offline by default.

## Evaluation

The evaluation harness lives in `eval/`. Three evaluators against a
hand-labeled synthetic benchmark:

| Evaluator | Metric | Where |
| --- | --- | --- |
| Extraction | per-field exact-match after typed normalization (trim+casefold for strings, ISO canonical for dates, ±0.01 for numbers); reports micro / macro / per-field accuracy + per-field precision/recall | `eval/labels/extraction_labels.json` |
| Retrieval | precision@k, recall@k, MRR (k=5) | `eval/labels/retrieval_labels.json` |
| RAG | citation-validity rate, answer-cites-relevant rate, expected-substring-match rate, refusal rate | `eval/labels/rag_labels.json` |

**Honesty discipline.** Under either fake provider, the harness emits
`n/a (...)` and refuses to write a numerical result for the affected metric;
this is the n/a gate that keeps Golden Rule #5 ("never fabricate evaluation
numbers") enforced in code. `eval/RESULTS.md` therefore ships in a
**PENDING / methodology-only** state until a real-provider run produces real
numbers — see [issue #13](https://github.com/div0rce/sentinel/issues/13).

The full methodology defense (every metric choice, normalization rule, and
honesty caveat) is in [`docs/evaluation.md`](docs/evaluation.md).

Reproduce the numbers locally:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export LLM_PROVIDER=anthropic
export EMBEDDINGS_PROVIDER=openai
make migrate && make seed && make eval
```

## Governance & guardrails

Three pillars, all deterministic and tested:

1. **Citation-or-refuse.** `rag.answer_query` requires the LLM to emit
   `[chunk:N]` markers and refuses if any cited id wasn't in the retrieval
   set. The same rule applies field-by-field in extraction. Source:
   `backend/app/rag.py`, `backend/app/extract.py`.

2. **PII redaction.** A registry of named regex patterns
   (`EMAIL`, `SSN`, `CREDIT_CARD`, `PHONE`, `IPV4`) replaces matches with
   `[REDACTED:KIND]`. Idempotent: a second pass over redacted output is a
   no-op. Runs **pre-storage** (chunks at ingest) and **pre-LLM** (the
   prompt sent to Claude). Toggle via `PII_REDACTION_ENABLED` (default
   `true`). Source: `backend/app/guardrails.py`. Specification:
   [`docs/guardrails.md`](docs/guardrails.md).

3. **Confidence gating + HITL routing.** Per-field confidence below
   `CONFIDENCE_REVIEW_THRESHOLD` (default `0.75`) sets `requires_review=true`
   on the extraction. The deterministic FSM in `backend/app/workflow.py`
   routes to one of three states (`auto_approved`, `needs_review`,
   `rejected`) and is idempotent: re-routing the same extraction never
   creates a second `workflow_items` row. Specification:
   [`docs/workflow.md`](docs/workflow.md).

Every model suggestion and every human decision writes exactly one
`audit_events` row in the same transaction as the state change. The
repository layer has no `update` or `delete` path; replaying an item's
events reproduces its current state. Specification:
[`docs/audit-and-review.md`](docs/audit-and-review.md).

## Deployment

The M10 Terraform stack provisions an ephemeral demo deployment in `us-east-1`:

- VPC with two public subnets, no NAT Gateway (cost posture; the avoided
  NAT Gateway is the largest avoidable line item — ~$32/month idle).
- ECS Fargate behind an ALB. Frontend (nginx serving the Vite SPA) is the
  default target. Backend (FastAPI) receives `/health` directly from the
  ALB; everything else under `/api/*` is reverse-proxied by nginx and the
  `/api` prefix is stripped before reaching FastAPI.
- RDS Postgres 16 (`db.t4g.micro`, single-AZ). Hard invariant:
  `publicly_accessible = false`; the security group only permits ingress
  from the backend task SG.
- ECR for the two images, SSM Parameter Store for runtime secrets (API keys
  and `DATABASE_URL`), and a tightly scoped GitHub Actions OIDC role for CI.

Estimated idle cost: **~$45/month**, dominated by the ALB + Fargate + RDS.

CD is **manual-dispatch only** via `.github/workflows/cd.yml`. There is no
`push:` or `pull_request:` trigger; the trigger gate is the cost-control
mechanism. The CD job assumes the OIDC role, builds and pushes images to
ECR, and force-redeploys the ECS services.

The full operator runbook (apply / write secrets / deploy / destroy) and
the cost-and-security posture rationale live in
[`infra/README.md`](infra/README.md). **`terraform destroy` immediately
after capturing screenshots** is the documented contract.

## Limitations & synthetic-data disclaimer

This is a portfolio project. The honest limitations:

- **All data is synthetic.** The corpus under `data/sample/` is generated
  deterministically by `scripts/gen_synthetic_corpus.py` with a fixed seed.
  No real customer documents have ever been ingested. Performance on real,
  noisy production documents will differ.
- **The eval set is small.** Five invoices for extraction, six retrieval
  queries, five RAG questions. Numbers from this set should be treated as
  **smoke-level signal**, not statistically significant accuracy claims.
  Expanding the labeled set is on the post-M11 backlog; the current
  pending/methodology-only state of `eval/RESULTS.md` is documented in
  [`docs/evaluation.md`](docs/evaluation.md).
- **No real-provider numbers committed yet.** `eval/RESULTS.md` ships in
  PENDING state. Real-provider numbers depend on a one-time `make eval` run
  with paid API keys, tracked in
  [issue #13](https://github.com/div0rce/sentinel/issues/13).
- **Demo-only deployment posture.** Single-AZ RDS, no Multi-AZ, no
  auto-scaling, no remote Terraform state, no TLS certificate by default
  (the ALB SG already permits 443; attach an ACM cert and add a 443
  listener to enable). See `infra/README.md` for the full list of
  production-readiness gaps.
- **Self-reported confidence is a routing signal, not a calibrated
  probability.** The M4 extraction schema collects per-field confidence
  from the LLM itself; it's used to route low-confidence fields to a human
  reviewer (M5/M6) but is **not** reported as calibrated probability in
  the evaluation harness. Calibrating model self-assessment is its own
  research surface.
- **Citation-validity is an in-context check.** It verifies that a cited
  chunk id is in the retrieval set, not that the cited chunk *actually
  contains* the supporting fact. The `cites-relevant` evaluator is the
  closest the harness gets to "the cited chunk is the right one"; an
  LLM-judge faithfulness check is the natural next step and is out of M9
  scope.

## Roadmap

Built to date (PRs in the GitHub history):

- M0 — Scaffolding, tooling, CI
- M1 — Data model + migrations (pgvector)
- M2 — Ingestion + embeddings
- M3 — Retrieval + citation-grounded RAG
- M4 — Schema-constrained structured extraction
- M5 — Guardrails (PII redaction, confidence gating)
- M6 — Deterministic, idempotent workflow engine
- M7 — Append-only audit log + HITL approval
- M8 — Frontend (Query, Review, Dashboard)
- M9 — Evaluation harness + methodology defense
- M10 — Containerization + Terraform (AWS) + manual CD
- M11 — Docs, architecture diagram, demo (this PR)

Post-M11 backlog (tracked in `MILESTONES.md`):

- Multi-tenant separation; role-based access on the review queue.
- Eval expansion (larger labeled set, per-category breakdown,
  LLM-judge faithfulness).
- Observability: OpenTelemetry traces, dashboards.
- Production-readiness for the AWS deploy: Multi-AZ RDS, private subnets +
  NAT or VPC endpoints, ACM/ALB TLS, S3 + DynamoDB Terraform backend.

## Project map

```
sentinel/
├── README.md MILESTONES.md PROGRESS.md AGENTS.md
├── Makefile pyproject.toml uv.lock .pre-commit-config.yaml .env.example
├── docker-compose.yml .dockerignore
├── .github/workflows/{ci.yml, cd.yml}
├── backend/
│   ├── app/
│   │   ├── main.py config.py db.py models.py observability.py
│   │   ├── embeddings/  # interface + OpenAI + Fake
│   │   ├── llm/         # interface + Claude + Fake
│   │   ├── ingest.py retrieval.py rag.py extract.py
│   │   ├── guardrails.py workflow.py audit.py
│   │   ├── extraction_schemas/  # Pydantic schemas registered with the extractor
│   │   ├── repositories/        # documents, chunks, extractions, workflow_items, audit_events
│   │   └── routers/             # query, extract, review, dashboard, health
│   ├── alembic/  # migrations
│   ├── tests/    # 195 pytest, runs against the CI Postgres+pgvector service
│   └── Dockerfile
├── frontend/
│   ├── src/{App.tsx, api.ts, views/{Query,Review,Dashboard}.tsx, ...}
│   ├── nginx.conf.template Dockerfile
│   └── tests via Vitest under src/__tests__/ and src/views/__tests__/
├── eval/                       # labels, harness, normalize, results, RESULTS.md
├── data/sample/                # SYNTHETIC corpus + README marking it synthetic
├── infra/                      # Terraform (network, ecr, rds, ecs, secrets, ci_oidc)
├── docs/
│   ├── architecture.md architecture.mmd architecture.png
│   ├── demo.md
│   ├── guardrails.md workflow.md audit-and-review.md evaluation.md
│   └── adr/
└── scripts/                    # gen_synthetic_corpus.py and friends
```

## License

[MIT](LICENSE).

---

> Built as a portfolio project. Issues and PRs welcome; see
> [`AGENTS.md`](AGENTS.md) and [`MILESTONES.md`](MILESTONES.md) for the
> milestone-driven workflow that produced the codebase.
