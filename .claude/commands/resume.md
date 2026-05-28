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
