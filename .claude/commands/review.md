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
