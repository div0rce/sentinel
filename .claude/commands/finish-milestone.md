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
