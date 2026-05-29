# Sentinel evaluation results

> **Status:** PENDING — no real-provider run has been recorded yet.
>
> Per CLAUDE.md Golden Rule #5, no numerical metric ships in this
> file until `make eval` has been executed against real `LLM_PROVIDER`
> and `EMBEDDINGS_PROVIDER`. The metric definitions, dataset shape, and
> provider/model slots below describe the harness contract; numbers
> appear when a real run overwrites this file.

All sample data is synthetic. See `docs/evaluation.md` for methodology.

## Run metadata

- **Run at (UTC):** _Numbers pending real-provider run_
- **LLM provider:** _pending_ (target: `anthropic`)
- **LLM model:** _pending_ (target: `claude-sonnet-4-6`)
- **Embedding provider:** _pending_ (target: `openai`)
- **Embedding model:** _pending_ (target: `text-embedding-3-small`)
- **Embedding dim:** `1536`
- **LLM temperature:** `0.0`
- **Retrieval k:** `5`

## Extraction (field-level accuracy)

Metric definition: per-field exact-match after documented normalization
(`eval/normalize.py`): trim + case-fold for strings, ISO canonicalisation
for date strings, and a 0.01 absolute tolerance for numbers. Reports
micro-accuracy (over all field slots), macro-accuracy (mean over per-field
accuracies), per-field accuracy, and per-field precision/recall (which
distinguishes wrong-value from missing-field for any optional/nullable
field).

- **Documents in dataset:** see `eval/labels/extraction_labels.json`
- **Micro accuracy:** _Numbers pending real-provider run_
- **Macro accuracy:** _Numbers pending real-provider run_
- **Per-field accuracy / P / R:** _Numbers pending real-provider run_
- **Failed extractions:** _Numbers pending real-provider run_

## Retrieval (precision@k, recall@k, MRR)

Metric definitions:

- `precision@k = |relevant ∩ top_k| / k`, averaged across queries.
  Note: precision@k is structurally capped at `min(1, |relevant|/k)`,
  so it reads pessimistic on queries where `|relevant| < k`. Reported as
  the headline number with this footnote.
- `recall@k = |relevant ∩ top_k| / |relevant|`, averaged.
- `MRR = mean(1 / rank_of_first_relevant_in_top_k)`; `0` if no relevant
  chunk appears in the top k for that query.

- **Queries in dataset:** see `eval/labels/retrieval_labels.json`
- **k:** `5`
- **precision@k / recall@k / MRR:** _Numbers pending real-provider run_

## RAG (citation-validity, answer cites relevant, lite faithfulness)

Metric definitions:

- **Citation-validity rate:** for each answered query, the fraction of
  cited `[chunk:N]` ids that are present in the retrieved set; averaged.
  Production code already enforces this (M3 invalid_citation refusal).
  Reporting the rate here lets a regression in the prompt or LLM be
  spotted before it triggers user-visible refusals.
- **Answer-cites-relevant rate:** fraction of answered queries whose
  cited chunks intersect the labeled-relevant set. Lite faithfulness
  proxy without an LLM judge.
- **Answer-substring match rate:** fraction of answers containing the
  expected substring (case-insensitive). Sanity check; not faithfulness.
- **Refusal rate:** fraction of questions where the M3 citation-or-refuse
  policy refused. Reported but not interpreted as quality.

- **Questions in dataset:** see `eval/labels/rag_labels.json`
- **Citation-validity / cites-relevant / substring / refusals:** _Numbers pending real-provider run_

## Notes

Per CLAUDE.md Golden Rule #5, this file reports **only real numbers** from a real-provider run. Sections marked `_pending_` are intentional placeholders and must not be misread as zero-valued metrics.
