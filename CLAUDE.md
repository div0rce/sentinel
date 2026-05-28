# CLAUDE.md — Sentinel

> **Project memory for Claude Code. Auto-loaded every session. Keep it current.**
> Starting or resuming work? Read this file → then `PROGRESS.md` → then `MILESTONES.md`.
> Do not write code until you have read all three and run `/resume`.

---

## What Sentinel is

Sentinel is a **Governed Document Intelligence Platform**: an enterprise RAG system that turns
an unstructured-document corpus into (a) **source-cited natural-language answers** and
(b) **schema-structured records with per-field confidence**, then routes those records through a
**deterministic, idempotent, human-in-the-loop workflow** with an **immutable audit trail**.

This is a portfolio project demonstrating enterprise-grade, auditable AI for regulated industries.
**All data is SYNTHETIC.** Never claim production use, real users, or real PII/PHI anywhere
(code, docs, commit messages, README).

---

## Golden rules (non-negotiable)

1. **Never commit or push to `main`.** All work happens on a feature branch. This is enforced by a
   `no-commit-to-branch` pre-commit hook and (server-side) GitHub branch protection. Do not bypass it.
2. **One milestone = one feature branch = one squash-merge PR.** Branch name: `feat/mNN-slug`
   (slug is defined per milestone in `MILESTONES.md`).
3. **Conventional Commits** on the branch: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`, `ci:`.
   Small, logical commits are encouraged — they make the squashed history honest and readable.
4. A milestone is **DONE** only when: every item in its Definition of Done (`MILESTONES.md`) is met,
   `make check` passes (lint + types + tests), and `PROGRESS.md` is updated.
5. **Never fabricate evaluation numbers.** Metrics exist only after the eval harness (M9) runs against
   the labeled benchmark. Report real numbers; if not yet measured, write "not measured" — never a guess.
6. **All sample and benchmark data is synthetic** and labeled as such in-repo (`data/sample/README.md`).
7. **No secrets in git.** Use `.env` (gitignored) locally and CI / cloud secret stores otherwise.
8. **Small, reviewable diffs.** If a milestone balloons past ~400 changed lines of real logic, split the PR
   and note the split in `MILESTONES.md`.
9. **Do not merge your own PRs.** Opening the PR is your job; squash-merging is the human's gate.

---

## Operating model (AI-first, human-in-the-loop)

- **You (Claude Code)** do: planning, branch creation, implementation, tests, `make check`, doc/state
  updates, commits, and opening the PR. You self-verify with the test suite before every PR.
- **The human** does: reads the PR, approves, and **squash-merges**. That merge is the only human gate.
- Resumability is anchored in `PROGRESS.md` + git history. After any interruption, the next session
  reconstructs state from those, never from assumption.

---

## Tech stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic
- **DB:** PostgreSQL 16 + `pgvector`
- **AI:** Anthropic Claude API for generation/extraction; embeddings via a hosted provider
  (`text-embedding-3-small` or `voyage-3-lite`) **behind an interface** in `backend/app/llm/` and
  `backend/app/embeddings/` so both are swappable and **mocked in tests** (no live API calls in CI).
- **Frontend:** React + TypeScript (Vite), Recharts
- **Infra:** Docker + docker-compose (dev); Terraform → AWS ECS Fargate + RDS (M10)
- **CI/CD:** GitHub Actions
- **Tooling:** `uv`, `ruff` (lint + format), `mypy`, `pytest`, `pre-commit`

---

## Target layout

```
sentinel/
├── CLAUDE.md MILESTONES.md PROGRESS.md HANDOFF.md README.md
├── Makefile pyproject.toml .pre-commit-config.yaml .gitignore .env.example
├── docker-compose.yml
├── .claude/{commands/, settings.json}
├── .github/{workflows/ci.yml, pull_request_template.md}
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + routers
│   │   ├── config.py          # pydantic-settings
│   │   ├── db.py models.py schemas.py
│   │   ├── embeddings/        # interface + provider + fake (tests)
│   │   ├── llm/               # interface + Claude client + fake (tests)
│   │   ├── ingest.py retrieval.py rag.py extract.py
│   │   ├── guardrails.py workflow.py audit.py
│   │   └── routers/{query.py, extract.py, review.py, dashboard.py, health.py}
│   ├── alembic/
│   └── tests/
├── frontend/                  # Vite + React + TS (M8)
├── eval/                      # labeled benchmark + scripts + RESULTS.md (M9)
├── infra/                     # Terraform (M10)
├── data/sample/               # SYNTHETIC corpus (+ README marking it synthetic)
└── docs/{architecture.md, demo.md, adr/}
```

> The exact tree is created in M0. Update this section if structure changes.

---

## Commands (created in M0; keep in sync with the Makefile)

- `make dev` — run backend + Postgres locally
- `make check` — `ruff check` + `ruff format --check` + `mypy` + `pytest` (**run before every PR**)
- `make test` / `make lint` / `make fmt`
- `make migrate` — apply migrations; `make migration m="msg"` — autogenerate one
- `make seed` — ingest the synthetic sample corpus
- `make eval` — run the evaluation harness (M9+)

---

## Workflow per milestone

1. `/resume` to confirm state.
2. `/start-milestone NN` → clean tree check, `git switch main && git pull --ff-only`, create `feat/mNN-slug`.
3. Implement in small commits; **write tests alongside code**.
4. `make check` must pass.
5. Update `PROGRESS.md` (status, what changed, next action, any decision → also add an ADR if architectural).
6. `/finish-milestone` → verify DoD, push branch, open PR with the template.
7. Human squash-merges. Then `git switch main && git pull --ff-only && git branch -d feat/mNN-slug`.

---

## Testing philosophy

- **Hard-test all deterministic logic:** chunking, the workflow engine, guardrails, the audit log.
- **Mock LLM + embeddings** in tests via the `fake` implementations; CI runs offline with no API keys.
- **Workflow engine MUST have explicit determinism + idempotency tests** (same input → same output;
  re-run → no duplicate side effects).
- **Audit log MUST be append-only;** include a test that reconstructs current state by replaying events.
- A Postgres + pgvector service runs in CI (see `.github/workflows/ci.yml`). No mocking the DB.

---

## Guardrails the app enforces (keep them enforced)

- **Citation-or-refuse:** never answer without a supporting retrieved source above threshold.
- **PII redaction:** applied before LLM calls and before storage.
- **Confidence gating:** low-confidence extractions route to human review; never auto-applied.
- **Audit everything:** every model suggestion and every human decision writes an audit event.

---

## House style

- Type hints everywhere; `mypy` clean. Pydantic models for all I/O boundaries.
- Docstrings on public functions; comments explain **why**, not **what**.
- No dead code; no `TODO`s left in merged PRs (move them to the `MILESTONES.md` backlog).
- Deterministic-by-default: seed any randomness; pin temperatures for LLM calls used in eval.
