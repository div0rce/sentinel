# Evaluation methodology

This document is the methodology defense for the Sentinel evaluation harness. The
intended audience is "an interviewer asking how you measured this" — every metric
choice, normalization rule, and reporting discipline is here so the answer to
"how did you compute that number?" is one paragraph plus a code reference, not a
hand-wave.

The harness lives in `eval/`. The committed `eval/RESULTS.md` is the sole source
of quotable numbers. Per CLAUDE.md Golden Rule #5 it ships in a **PENDING /
methodology-only** state until a real-provider run produces real numbers; nothing
else in the repo is a quotable performance claim.

## Dataset

Hand-authored synthetic ground truth keyed against the existing committed
synthetic corpus under `data/sample/` (generator: `scripts/gen_synthetic_corpus.py`,
seed `20260528`). Three label files:

| File | Items | What it labels |
| --- | --- | --- |
| `eval/labels/extraction_labels.json` | 5 invoices | Per-document expected payload (4 fields each → 20 field-slots) |
| `eval/labels/retrieval_labels.json` | 6 queries | Relevant chunks per query, k=5. One query has #relevant=2 to exercise recall@k. |
| `eval/labels/rag_labels.json` | 5 questions | Relevant chunks + an expected substring the answer should contain |

Everything is synthetic and labeled as such in-repo (`data/sample/README.md`,
`AGENTS.md` reminder, in-document boilerplate in every generated file). Sample
size is small by design — large enough to surface real bugs in the harness and
the prompts, small enough that a reviewer can audit every label.

Bigger labeled sets are tracked in `MILESTONES.md`'s post-M11 backlog.

## Provider pinning

Quotable numbers come from a real-provider run with these pins (recorded with
the run in `eval/RESULTS.md`):

- **LLM:** `claude-sonnet-4-6` (Anthropic). Verified against
  https://docs.anthropic.com/en/docs/about-claude/models on 2026-05-29; the
  4.6-generation IDs use a dateless format that *is* a pinned snapshot, not an
  evergreen pointer (see Anthropic's "Model IDs and versioning").
- **Embedding:** `text-embedding-3-small` (OpenAI), 1536 dimensions, matching
  `backend.app.models.SCHEMA_EMBEDDING_DIM`.
- **Temperature:** `0.0` per CLAUDE.md house style ("pin temperatures for LLM
  calls used in eval").
- **k:** `5` for retrieval and as the default top-k passed to RAG.

`Settings` defaults reflect these pins; `.env.example` documents them.

## Metrics

### 1. Extraction accuracy

**Definition.** For each labeled `(document, schema_name, expected_payload)`
triple, run the M4 `extract.extract_document` and compare each extracted field's
value to the ground truth. Comparison is **exact-match after documented per-
field-type normalization** (`eval/normalize.py`):

- **Strings** — `str.strip().casefold()`. Internal whitespace preserved.
- **ISO dates** (`YYYY-MM-DD`) — parsed and re-emitted via `date.fromisoformat`
  to canonicalise. Non-ISO date strings fall through to the string rule (a
  non-ISO answer is wrong by the schema, which is the right outcome).
- **Numbers** — coerced to `float`, rounded to 2 decimals, and compared with an
  absolute tolerance of `0.01`.
- `None` — preserved; only equals `None`.

Why normalize. Raw exact-match deflates accuracy for cosmetic reasons (`"Dr.
Smith"` vs `"Smith"`, `"3/4/25"` vs `"2025-03-04"`). Normalization documents
exactly which transformations are applied and makes the metric explainable
without forgiving wrong answers.

**Reported quantities.**

- **Micro-accuracy** — fraction of correct field-slots across all documents.
  This is the headline number on the résumé.
- **Macro-accuracy** — mean of per-field accuracies across the schema. Catches
  cases where the harness happens to be right on most fields but bad on one.
- **Per-field accuracy** — per `(field_name, all docs)`. The interview answer
  to "what does the model get right vs wrong?".
- **Per-field precision/recall** — for any optional/nullable field, this
  distinguishes wrong-value (precision down, recall down) from missing-field
  (precision unchanged because nothing was extracted, recall down). M4's
  `InvoicePayload` has all required fields, so per-field P/R degenerates to
  the accuracy values for that schema; the column is reported regardless so a
  future schema with optional fields gets the right reading without a code
  change.

**Failure handling.** A document that fails extraction (parse error, schema
invalid, invalid citation, etc.) does *not* contribute to accuracy and is
counted in `failed_extractions`. This is how the harness avoids conflating
"the LLM produced something wrong" with "the LLM didn't produce anything".

### 2. Retrieval — precision@k, recall@k, MRR

**Definitions** (averaged across labeled queries):

- `precision@k = |relevant ∩ top_k| / k`
- `recall@k = |relevant ∩ top_k| / |relevant|`
- `MRR = mean(1 / rank_of_first_relevant_in_top_k)`; `0` if no relevant chunk
  appears in the top-k for that query.

**Headline number is precision@k**, with a footnote: precision@k is structurally
capped at `min(1, |relevant|/k)`, so on any query where `|relevant| < k` the
metric reads pessimistic for a non-retrieval reason. Recall@k and MRR exist to
remove that artifact and to give the interview a richer answer than a single
number — they're cheap given the relevance labels are already in hand.

**Why no nDCG.** The labels are binary relevance, so DCG/nDCG would degenerate
to the same information that recall@k captures. Adding it would be cosmetic.

### 3. RAG — citation-validity, cites-relevant, lite faithfulness

For each labeled `(question, relevant_chunks, expected_substring)` triple, run
the M3 `rag.answer_query` and report:

- **Citation-validity rate** — for each answered query, the fraction of cited
  `[chunk:N]` ids that are present in the retrieved set. Production code
  already enforces this (M3 `invalid_citation` refusal); reporting the rate
  catches regressions in the prompt or LLM before they cause user-visible
  refusals.
- **Answer-cites-relevant rate** — fraction of answered queries where the cited
  chunk set intersects the labeled-relevant set. This is the lite-faithfulness
  proxy: a faithful answer should at least cite a chunk that contains the
  ground-truth answer.
- **Answer-substring match rate** — fraction of answers (case-insensitive)
  containing the labeled expected substring. Sanity check, not faithfulness;
  reported because it's free given the labels and it surfaces obvious
  hallucinations cheaply.
- **Refusal rate** — fraction of questions where the M3 citation-or-refuse
  policy refused. Reported but **not interpreted as quality**; an honest
  refusal is correct behaviour when retrieval is bad.

**No LLM-judge faithfulness.** That would confound the metric we're measuring
(the system uses an LLM; using another LLM to grade introduces a covariate we
can't characterise on a synthetic corpus this small). It's correctly out of
scope for M9.

**No ROUGE/BLEU.** Cosmetic vanity for RAG; correlates poorly with answer
correctness on small extractive tasks.

## Honesty discipline (the n/a gate)

Under either fake provider, the harness emits `n/a (...)` and refuses to write
a numerical result for the affected metric:

| Setting | Affected metric(s) |
| --- | --- |
| `EMBEDDINGS_PROVIDER=fake` | retrieval (precision@k / recall@k / MRR), RAG (all arms — retrieval feeds them) |
| `LLM_PROVIDER=fake` | extraction, RAG (all arms — the LLM produces the answer) |

The dataset counts (`n_documents`, `n_queries`, `n_questions`,
`failed_extractions`, `refusals`) are still emitted because they describe the
dataset and harness behaviour, not the system's quality.

A scripted-fake run is **harness validation only and emits no quotable
number**. The asserted-fixture pytest tests
(`backend/tests/test_eval_harness.py`) prove the scorer + writer work without
ever shipping a number that could be misread as a quality claim.

## Reproducing the numbers

```bash
# 1. Wire keys (real run)
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export LLM_PROVIDER=anthropic
export EMBEDDINGS_PROVIDER=openai

# 2. Apply migrations to a fresh DB
make migrate

# 3. Seed the synthetic corpus
make seed

# 4. Run the eval and overwrite RESULTS.md
make eval

# 5. Inspect; commit RESULTS.md alongside the PR
cat eval/RESULTS.md
```

The harness reads from the labels under `eval/labels/`, ingests any referenced
file that isn't already in the DB, and prints a one-line summary per metric
plus the path to the written file.

## Limits and honest caveats

- **Dataset size is small.** Five invoices for extraction, six retrieval
  queries, five RAG questions. Numbers from this set should be treated as
  **smoke-level signal**, not statistically significant accuracy claims. The
  M11 backlog has "expand the labeled set" as an explicit task.
- **Synthetic corpus.** Real production performance on real invoices may
  differ; the synthetic generator produces clean, well-formatted documents
  with consistent layouts, and an LLM is likely to do better here than on
  noisy scanned PDFs.
- **Self-reported confidence.** The M4 extraction schema collects per-field
  confidence from the LLM itself. We use it as a routing signal (M5
  guardrails, M6 workflow) but **do not** report confidence-vs-accuracy
  calibration in M9 because calibrating model self-assessment is its own
  research surface.
- **Citation-validity is an in-context check.** It does not validate that the
  cited chunk *actually contains* the supporting fact, only that it was in the
  retrieval set. The cites-relevant rate is the closest M9 gets to "the cited
  chunk is the right one"; an LLM-judge faithfulness check would close the
  gap and is the natural M11+ extension.

## Where to look in the code

| Concern | File |
| --- | --- |
| Metric definitions and dataclasses | `eval/harness.py` |
| Per-field-type normalization rules | `eval/normalize.py` |
| RESULTS.md writer (real run + pending) | `eval/results.py` |
| CLI used by `make eval` | `eval/run.py` |
| Asserted scorer/writer behaviour | `backend/tests/test_eval_harness.py` |
| Settings (model, embedder, temperature, k) | `backend/app/config.py` |
| Label files | `eval/labels/*.json` |

## Cross-references

- **CLAUDE.md Golden Rule #5** — never fabricate evaluation numbers.
- **PROGRESS.md "Decision log"** — every M9 decision is recorded with date and
  rationale.
- **MILESTONES.md M9** — DoD scope.
