"""Sentinel evaluation harness (M9).

Hand-authored synthetic ground truth labels under :mod:`eval.labels` are scored
against the running pipeline by :mod:`eval.harness`. The CLI (``eval.run``,
invoked by ``make eval``) writes :file:`eval/RESULTS.md`.

All labels and corpus content are synthetic. Any quotable metric in
``RESULTS.md`` must come from a real-provider run; under fake providers the
harness emits ``n/a`` and refuses to publish a number.
"""
