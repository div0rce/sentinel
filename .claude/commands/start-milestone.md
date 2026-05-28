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
