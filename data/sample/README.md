# Sample data — SYNTHETIC

**All data in this directory is synthetic.** It is generated solely for development,
testing, and demonstration. It does not represent real people, organizations, events,
PII, or PHI. Sentinel makes no claim of production use or real data anywhere in this
repository.

## What's here

A small fictional corpus of three document types, all generated deterministically by
[`scripts/gen_synthetic_corpus.py`](../../scripts/gen_synthetic_corpus.py):

- `invoice_inv-*.md` — fictional vendor invoices with line items, subtotals, and tax.
- `incident_inc-*.md` — fictional plant-floor incident reports with narrative, root
  cause, and disposition sections.
- `policy_pol-*.md` — fictional internal policy memos with thresholds and audit cadence.

The generator is seeded so re-running it produces byte-identical files; the committed
corpus is therefore reproducible from the script.

## Re-generate

```
uv run python scripts/gen_synthetic_corpus.py
```

## Ingest

```
make seed     # uses EMBEDDINGS_PROVIDER, defaults to openai; CI sets it to fake
```
