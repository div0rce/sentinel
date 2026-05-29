# Guardrails

Sentinel's guardrails are a thin, deterministic safety layer that runs at fixed
points in the pipeline. There are three pillars:

1. **Citation-or-refuse** (M3) — never answer a question without retrieved support;
   never accept an extraction whose ``source_chunk_id`` is fabricated.
2. **PII redaction** (M5) — apply a deterministic regex pass to text **before** any
   LLM call and **before** storage.
3. **Confidence gating** (M5) — flag low-confidence extractions for review without
   blocking them; the M6 workflow engine consumes the flag.

This document covers (2) and (3). Citation-or-refuse details live in code at
``backend/app/rag.py`` and ``backend/app/extract.py``.

## PII redaction

### Patterns

The registry lives in ``backend/app/guardrails.py`` and ships with five named
patterns, listed more-specific-first so overlapping matches resolve correctly:

| Kind          | Shape                                              | Example                  |
| ------------- | -------------------------------------------------- | ------------------------ |
| `EMAIL`       | `<local>@<domain>.<tld>`                           | `john.doe@example.com`   |
| `SSN`         | `XXX-XX-XXXX` (US Social Security)                 | `123-45-6789`            |
| `CREDIT_CARD` | 16 digits in 4-4-4-4 groups (space or hyphen)      | `4111-1111-1111-1111`    |
| `PHONE`       | US formats (with optional country code, separators)| `(415) 555-0123`         |
| `IPV4`        | dotted-quad                                        | `10.0.0.1`               |

Each match is replaced verbatim with `[REDACTED:KIND]` (e.g. `[REDACTED:EMAIL]`).
Replacement text is chosen so it never re-matches any pattern, making the redaction
idempotent on a second pass.

### Algorithm

`redact_pii(text)` returns a `RedactionResult` with:

- `text` — the redacted string.
- `hits` — a list of `RedactionHit(kind, start, end, original)` entries, one per
  match, in left-to-right order in the original text.

Determinism: the function depends only on the input string and the compiled
regex registry. There is no randomness, no I/O, and no global state beyond the
registry. Identical input always yields identical output.

Resolution: each pattern scans the original text in registry order; matches that
overlap an earlier-claimed span are skipped. The output is built in a single
left-to-right pass against the union of accepted spans, so placeholders never
re-match downstream patterns.

### Where it runs

Two lines in the pipeline apply redaction; the toggle
`PII_REDACTION_ENABLED` (default `true`) gates both:

1. **Pre-storage** — `backend/app/ingest.py` redacts each chunk's text *before*
   `chunks_repo.bulk_insert`. The database therefore stores only redacted chunk
   text. The document hash is computed on the **original** text, so re-ingesting
   the same source still short-circuits via the hash check (no duplicate documents).
2. **Pre-LLM** — `backend/app/rag.py::_build_user_prompt` redacts the question and
   each chunk's text. `backend/app/extract.py::_build_user_prompt` redacts each
   chunk's text in the context block. Live user input is redacted at request time.

### Idempotency and re-ingest

Toggling `PII_REDACTION_ENABLED` does not retroactively redact rows already in the
database. To redact an existing corpus:

1. Truncate `chunks` (or drop and re-`make migrate`).
2. Re-run `make seed` (or your ingest CLI) with `PII_REDACTION_ENABLED=true`.

The hash on `documents.hash` is a content fingerprint of the **original** text,
which means re-ingesting the same content with redaction enabled will produce a
duplicate-document conflict if the previous documents row still exists. Truncate
documents and chunks together if you want to start over.

### Disabling redaction

`PII_REDACTION_ENABLED=false` in `.env` disables both call sites. This is intended
only for local debugging against synthetic input you control. The default is
`true` and CI keeps it `true`.

## Confidence gating

### Helpers

`backend/app/guardrails.py` exposes two pure helpers:

```python
low_confidence_fields(field_confidence: Mapping[str, float], *, threshold: float) -> list[str]
requires_review(field_confidence: Mapping[str, float], *, threshold: float) -> bool
```

`low_confidence_fields` returns names whose confidence is **strictly below**
`threshold`, in insertion order. `requires_review` is `True` iff the list is
non-empty.

### Where it runs

`backend/app/extract.py::extract_document` populates two new fields on the
`ExtractionResult` it returns (and on the `POST /extract` response):

- `requires_review: bool`
- `low_confidence_fields: list[str]`

Both are computed via the helpers above against
`settings.confidence_review_threshold` (default `0.75`). The flag is **purely
informational** at this layer — extractions are still validated, persisted, and
returned exactly as before. Routing low-confidence records to a human review queue
is the M6 workflow engine's job.

### Tuning

`CONFIDENCE_REVIEW_THRESHOLD` in `.env` (default `0.75`) controls the cutoff. The
M9 evaluation harness records the threshold value alongside any reported metric so
the choice is auditable.

## Configuration knobs

| Env var                       | Default | Description                                                       |
| ----------------------------- | ------- | ----------------------------------------------------------------- |
| `PII_REDACTION_ENABLED`       | `true`  | Toggle for pre-storage and pre-LLM redaction.                     |
| `CONFIDENCE_REVIEW_THRESHOLD` | `0.75`  | Per-field confidence cutoff used by `requires_review`.            |

## Wiring map

```
                     ┌───────────────────┐
                     │ ingest.ingest_*** │  pre-storage redaction (chunks)
                     └──────┬────────────┘
                            │
                            ▼
                     ┌───────────────────┐
                     │ chunks_repo       │  stores redacted text only
                     └──────┬────────────┘
                            │
       ┌────────────────────┴────────────────────┐
       ▼                                         ▼
┌───────────────────┐                   ┌───────────────────┐
│ rag.answer_query  │                   │ extract.extract_* │
│ (M3)              │                   │ (M4)              │
│  └ _build_user_…  │  pre-LLM redact   │  └ _build_user_…  │
└──────┬────────────┘                   └──────┬────────────┘
       │                                       │
       ▼                                       ▼
   LLMClient                              LLMClient
                                              │
                                              ▼
                                        ExtractionResult
                                          .requires_review
                                          .low_confidence_fields
```

## Testing

The M5 guardrail suite covers (see `backend/tests/test_guardrails.py` and the
extensions to `test_ingest.py` / `test_rag.py` / `test_extract.py`):

- Each PII pattern matches the canonical shapes and ignores common false-positive
  variants.
- `redact_pii` is idempotent: a second pass over redacted output is a no-op.
- Hits report correct kind, span, and original text.
- Empty input and PII-free input pass through unchanged.
- `low_confidence_fields` and `requires_review` agree with their definition across
  edge cases (empty map, all-high, all-low, exact threshold).
- Pre-storage redaction at ingest produces chunk rows whose stored text contains
  `[REDACTED:KIND]` markers.
- Pre-LLM redaction at query / extract time produces a prompt the FakeLLM
  observes with PII replaced.
- `extract_document` sets `requires_review=True` exactly when at least one field's
  confidence is below the configured threshold.
