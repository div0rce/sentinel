# HANDOFF.md — How to build Sentinel with Claude Code

This is your operator's manual. It tells you **which tool to use**, how to set the repo up so an AI can
drive it efficiently, how to build in resumable milestones, and exactly what to paste to start and to
resume. The repo "brain" lives in three companion files — `CLAUDE.md` (rules), `MILESTONES.md` (the plan),
`PROGRESS.md` (live state). Keep all four in the repo root.

---

## 0. Use Claude Code, not Cowork

**Build Sentinel with Claude Code.** It is the agentic coding tool: it edits files, runs git and tests,
manages branches, and opens PRs from your terminal/IDE — exactly this workload.

**Cowork** is the agentic app for *non-developer knowledge work* (docs, research, analysis, slides). It is
the wrong tool for a full-stack repo with a git/PR workflow. Optional use: after the build, Cowork can help
draft the case-study writeup or polish the résumé — but the engineering is Claude Code, start to finish.

> Claude Code is **stateless between sessions** (it forgets the conversation when you close it) but
> remembers via files. That is why `CLAUDE.md` + `PROGRESS.md` exist and why this whole setup is
> file-anchored: it survives running out of tokens, crashes, and walking away for a week.

---

## 1. One-time setup (≈15 min)

1. **Install Claude Code** (Node 18+):
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
   Run `claude` in any folder once to authenticate. (Docs: https://docs.claude.com/en/docs/claude-code/overview)
2. **Install supporting tools:** `git`, `gh` (GitHub CLI — `gh auth login`), Docker, and `uv`
   (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
3. **Create an empty private repo** on GitHub (no README) and clone it. Name it `sentinel`.
4. **Drop these four files into the repo root:** `CLAUDE.md`, `MILESTONES.md`, `PROGRESS.md`, `HANDOFF.md`.
   Commit them on `main` once (this is the only direct-to-main commit you'll make), then push.
5. **Turn on branch protection** (this enforces "never work on main" server-side):
   ```bash
   gh api -X PUT repos/:owner/sentinel/branches/main/protection \
     -F required_pull_request_reviews.required_approving_review_count=0 \
     -F enforce_admins=false -F required_status_checks=null -F restrictions=null
   ```
   (Or do it in GitHub → Settings → Branches → add rule on `main`: "Require a pull request before merging".)
6. **API keys:** have an Anthropic API key (the app's LLM) and an embeddings key (OpenAI or Voyage). You'll
   put them in `.env` (gitignored) during M2/M3. **CI needs none** — tests mock both providers.

---

## 2. Kick it off

`cd` into the repo, run `claude`, and paste this:

```
Read HANDOFF.md, CLAUDE.md, MILESTONES.md, and PROGRESS.md in full before doing anything.

Then bootstrap the repo for Milestone M0:
- Create every scaffolding file listed in M0 using the templates in the HANDOFF.md appendix
  (.claude/commands/*, .claude/settings.json, .github/workflows/ci.yml,
   .github/pull_request_template.md, Makefile, pyproject.toml, .pre-commit-config.yaml,
   .gitignore, .env.example, docker-compose.yml, docs/ skeleton, data/sample/README.md).
- Follow every Golden Rule in CLAUDE.md. In particular: do NOT commit to main. Start by running
  /start-milestone 00 to create the feature branch first.
- Implement M0 to its Definition of Done, make `make check` and CI pass, update PROGRESS.md,
  then run /finish-milestone to open the PR. Stop and let me squash-merge it.

Work milestone by milestone. After each merge, wait for me, then continue with the next milestone.
```

Then for each milestone after M0, you just type `/start-milestone NN`, let it work, and `/finish-milestone`.
You review the PR on GitHub and **squash-merge**.

---

## 3. Resume after an interruption

Open `claude` in the repo and paste:

```
/resume
```

It reads `PROGRESS.md` + `MILESTONES.md`, checks `git status` / `git log` / open PRs, and reports the exact
next action. Confirm, then it continues. If you were mid-milestone, it picks up from the "Mid-milestone
scratch" note in `PROGRESS.md`. This is the whole point of the setup: you can always get back to work in one
line.

---

## 4. Why this layout is efficient for an AI (and how the human stays in the loop)

- **`CLAUDE.md`** is loaded into context automatically every session — the AI never re-learns your rules,
  stack, or commands. It is the single highest-leverage file.
- **Custom slash commands** (`/resume`, `/start-milestone`, `/finish-milestone`, `/review`) turn your
  repetitive workflow into one-word, deterministic actions.
- **Tests as guardrails** let the AI self-verify (`make check`) before asking you for anything. CI re-checks
  on every PR. The AI mocks the LLM/embeddings so CI is fast, free, and offline.
- **`PROGRESS.md` + git history** are the durable state. The AI reconstructs "where am I" from facts, not
  memory.
- **The human gate is exactly one action per milestone:** read the PR, squash-merge. Everything else is
  automated. That is "AI-first, human-in-the-loop."

---

## 5. Making the history look like clean human development

Three things produce a professional, human-looking git history automatically — no manipulation required:

1. **One feature branch per milestone, squash-merged.** `main` ends up with ~12 clean commits, one per
   milestone, each a logical unit. This is exactly what disciplined teams' histories look like.
2. **Conventional Commits** on the branch, and curated **squash-merge titles** (the PR titles in
   `MILESTONES.md`). The squashed commit on `main` reads like a human wrote it.
3. **Build across several sessions/days.** Real incremental work produces naturally spaced timestamps and a
   believable cadence (M0 → M11). This is also the honest answer to "how long did this take?" in an
   interview, so don't backdate commits — it's unnecessary and awkward to defend.

> **Co-author trailer:** by default Claude Code appends a "Co-authored-by: Claude" trailer to commits.
> Whether to keep it is your call and configurable in `.claude/settings.json` (see the docs for the current
> key). AI-assisted development is normal; the work and the repo are yours either way.

---

## 6. Skills, MCP, and Obsidian — what to actually use

Keep the toolbelt minimal. More tools = more failure surface.

**Use:**
- The four **custom commands** below — they are the real automation.
- **`gh` CLI** for PRs (Claude Code calls it directly). Don't bother with a GitHub MCP; the CLI is simpler.

**Optional, add only if it pays off:**
- A **current-docs MCP** (e.g., Context7-style) so the AI uses up-to-date FastAPI / pgvector / SQLAlchemy /
  Terraform APIs instead of stale memory. Worth it around M2, M3, and M10. Add per the docs:
  https://docs.claude.com/en/docs/claude-code/mcp
- A **frontend/design skill** for M8 if you want a more polished UI than default. Drop it under
  `.claude/skills/` and let the AI invoke it during the frontend milestone only.

**Skip for this project:**
- **Postgres MCP** — SQLAlchemy + `psql` already cover it.
- **Obsidian / Obsidian MCP** — your knowledge base *is* the repo (`CLAUDE.md`, `MILESTONES.md`,
  `PROGRESS.md`, `docs/`, ADRs), which Claude Code reads natively and which keeps state and code in one
  place. Adding Obsidian splits the source of truth for marginal benefit. If you already live in Obsidian,
  just **open the repo's `docs/` folder as a vault** (it's plain Markdown) for nicer reading/linking — no MCP
  needed. Only add the Obsidian MCP if you specifically want Claude to read/write a separate notes vault, and
  even then keep the repo as canonical.

---

# Appendix — scaffolding templates (M0 creates these)

> The AI will generate these in M0. They're here verbatim so the AI reproduces them faithfully and so you
> have them if anything drifts. Bump tool/action versions to current at build time.

### `.claude/commands/resume.md`
```markdown
---
description: Re-orient after an interruption; report exactly where the build stands and the next action.
allowed-tools: Read, Bash, Glob, Grep
---
You are resuming work on Sentinel. Do NOT write code yet.
1. Read CLAUDE.md, PROGRESS.md, and MILESTONES.md.
2. Run: `git status`, `git branch --show-current`, `git log --oneline -10`, and `gh pr list`.
3. Determine the in-progress or next milestone, whether an unmerged branch exists, and whether
   `make check` currently passes.
4. Report a short status: current milestone, branch state, last merged milestone, and the precise
   next action (cite the relevant DoD items).
5. Stop and wait for my confirmation before proceeding.
```

### `.claude/commands/start-milestone.md`
```markdown
---
description: Begin a milestone on a fresh feature branch. Usage: /start-milestone <NN>
allowed-tools: Read, Bash, Glob, Grep, Edit, Write
---
Start milestone $ARGUMENTS.
1. Read the M$ARGUMENTS spec in MILESTONES.md (goal, scope, files, Definition of Done).
2. Ensure a clean tree (`git status`). If dirty, stop and ask.
3. `git switch main && git pull --ff-only`.
4. Create the branch using the slug from MILESTONES.md: `git switch -c feat/m$ARGUMENTS-<slug>`.
5. Restate the Definition of Done as a checklist you will satisfy.
6. Plan in small steps, then implement. Write tests alongside code.
7. Mark this milestone "in progress" (with today's date) in PROGRESS.md.
```

### `.claude/commands/finish-milestone.md`
```markdown
---
description: Verify, document, commit, and open a squash-merge PR for the current milestone.
allowed-tools: Read, Bash, Glob, Grep, Edit, Write
---
Finish the current milestone.
1. Confirm EVERY Definition-of-Done item (MILESTONES.md) is met. If any gap remains, list it and stop.
2. Run `make check` (ruff + ruff-format + mypy + pytest). It must pass; fix failures first.
3. Update PROGRESS.md: mark the milestone complete, summarize what changed, set the next action,
   add any decision (and an ADR under docs/adr/ if architectural). Record measured numbers if this was M9.
4. Stage and commit with Conventional Commit messages (small logical commits are fine).
5. Push: `git push -u origin HEAD`.
6. Open a PR with `gh pr create` using .github/pull_request_template.md. Title = the milestone's PR title
   from MILESTONES.md. Body: scope summary, checked DoD list, test coverage notes.
7. Give me the PR URL and remind me to SQUASH-MERGE it. Do not merge to main yourself.
8. After I confirm the merge: `git switch main && git pull --ff-only && git branch -d <branch>`.
```

### `.claude/commands/review.md`
```markdown
---
description: Strict, independent self-review of the current branch vs the milestone DoD and house rules.
allowed-tools: Read, Bash, Glob, Grep
---
Critically review the current branch. Do NOT modify code.
1. `git diff main...HEAD`.
2. Check against the current milestone's Definition of Done and CLAUDE.md golden rules.
3. Flag: missing tests; non-deterministic logic without determinism tests; secrets in code;
   any fabricated/guessed metric; broken guardrails (citation-or-refuse, PII redaction, confidence
   gating, audit logging); dead code; type errors; unhandled errors; non-synthetic data claims.
4. Output a punch list split into BLOCKING and nice-to-have. Be strict.
```
> Tip: for an unbiased review with isolated context, you can instead make a `code-reviewer` **subagent**
> under `.claude/agents/` and have `/finish-milestone` delegate to it. Optional.

### `.claude/settings.json`
```json
{
  "permissions": {
    "allow": [
      "Read", "Edit", "Write", "Glob", "Grep",
      "Bash(git:*)", "Bash(gh:*)", "Bash(make:*)", "Bash(uv:*)",
      "Bash(pytest:*)", "Bash(ruff:*)", "Bash(mypy:*)", "Bash(alembic:*)",
      "Bash(docker:*)", "Bash(docker compose:*)", "Bash(terraform:*)"
    ],
    "ask": ["Bash(git push:*)"],
    "deny": []
  }
}
```
> Confirm the exact settings schema and the co-author-trailer key against current docs:
> https://docs.claude.com/en/docs/claude-code/settings . The reliable guard against committing to `main`
> is the `no-commit-to-branch` pre-commit hook below plus GitHub branch protection (Step 1.5).

### `.github/pull_request_template.md`
```markdown
## Milestone
M__ — <name>

## Summary
<what this PR delivers, 2–4 sentences>

## Definition of Done
- [ ] All DoD items from MILESTONES.md met
- [ ] `make check` passes (ruff + ruff-format + mypy + pytest)
- [ ] Tests added/updated for new logic
- [ ] PROGRESS.md updated
- [ ] No secrets committed; sample data is synthetic
- [ ] Guardrails intact (citation-or-refuse, PII redaction, confidence gating, audit logging) — if applicable

## Notes / decisions
<ADR links, tradeoffs, follow-ups>
```

### `.github/workflows/ci.yml`
```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  check:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: sentinel
          POSTGRES_PASSWORD: sentinel
          POSTGRES_DB: sentinel_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U sentinel" --health-interval 10s
          --health-timeout 5s --health-retries 5
    env:
      DATABASE_URL: postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel_test
      # LLM + embeddings are mocked in tests; no API keys in CI.
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy .
      - run: uv run pytest -q
```

### `.pre-commit-config.yaml`
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: no-commit-to-branch        # blocks commits on main/master — enforces Golden Rule #1
      - id: detect-private-key
      - id: check-merge-conflict
      - id: end-of-file-fixer
      - id: trailing-whitespace
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format
```

### `Makefile`
```makefile
.PHONY: dev check test lint fmt migrate migration seed eval
dev: ; docker compose up -d db && uv run uvicorn backend.app.main:app --reload
check: lint typecheck test
lint: ; uv run ruff check . && uv run ruff format --check .
typecheck: ; uv run mypy .
test: ; uv run pytest -q
fmt: ; uv run ruff format . && uv run ruff check --fix .
migrate: ; uv run alembic upgrade head
migration: ; uv run alembic revision --autogenerate -m "$(m)"
seed: ; uv run python -m backend.app.ingest --path data/sample
eval: ; uv run python -m eval.run && cat eval/RESULTS.md
```

### `.gitignore` (essentials)
```
.env
__pycache__/
.venv/
.mypy_cache/ .ruff_cache/ .pytest_cache/
node_modules/ dist/
*.log
.terraform/ *.tfstate *.tfstate.*
```

### `.env.example`
```
DATABASE_URL=postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel
ANTHROPIC_API_KEY=
EMBEDDINGS_PROVIDER=openai          # or: voyage
OPENAI_API_KEY=
VOYAGE_API_KEY=
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SCORE=0.30
CONFIDENCE_REVIEW_THRESHOLD=0.75
```

### `docker-compose.yml`
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: sentinel
      POSTGRES_DB: sentinel
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes: { pgdata: {} }
```

---

## Cost & safety reminders
- The cloud milestone (M10) can incur AWS charges. Gate deploys behind manual dispatch and **tear down with
  `terraform destroy` after capturing demo screenshots**.
- Never put real personal data in the corpus. The benchmark and sample data are synthetic and must be
  labeled as such (`data/sample/README.md`, README disclaimer).
- The évaluation numbers for your résumé come **only** from `make eval` (M9). Paste those real figures into
  the résumé's Sentinel bullet; do not estimate.
