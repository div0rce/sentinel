"""Render an :class:`eval.harness.HarnessReport` as the project's RESULTS.md.

The PENDING (no-numbers) version of this file is committed to the tree; running
``make eval`` overwrites it with metrics if the report contains quotable
numbers, or with explicit ``n/a (fake provider)`` markers when it does not.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from eval.harness import (
    ExtractionResult,
    HarnessReport,
    RagResult,
    RetrievalResult,
)

PENDING_HEADER = "Numbers pending real-provider run"


def render(report: HarnessReport, *, run_at: datetime | None = None) -> str:
    """Render the full RESULTS.md body."""
    run_at = run_at or datetime.now(UTC)
    lines: list[str] = []
    lines.append("# Sentinel evaluation results")
    lines.append("")
    lines.append("All sample data is synthetic. See `docs/evaluation.md` for methodology.")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- **Run at (UTC):** {run_at.isoformat()}")
    lines.append(f"- **LLM provider:** `{report.settings_summary['llm_provider']}`")
    lines.append(f"- **LLM model:** `{report.settings_summary['claude_model']}`")
    lines.append(f"- **Embedding provider:** `{report.settings_summary['embeddings_provider']}`")
    lines.append(f"- **Embedding model:** `{report.settings_summary['openai_embedding_model']}`")
    lines.append(f"- **Embedding dim:** `{report.settings_summary['embedding_dim']}`")
    lines.append(f"- **LLM temperature:** `{report.settings_summary['llm_temperature']}`")
    lines.append(f"- **Retrieval k:** `{report.settings_summary['retrieval_top_k']}`")
    lines.append("")

    lines.extend(_render_extraction(report.extraction))
    lines.append("")
    lines.extend(_render_retrieval(report.retrieval))
    lines.append("")
    lines.extend(_render_rag(report.rag))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "Per CLAUDE.md Golden Rule #5, this file reports **only real numbers** from "
        "the run above. Sections marked `n/a (...)` were produced by a fake "
        "provider and must not be quoted as system performance."
    )
    lines.append("")
    return "\n".join(lines)


def render_pending() -> str:
    """The methodology-only file committed to the tree.

    Identical structure to a real run, but every metric slot says
    ``Numbers pending real-provider run``. No fabricated numbers.
    """
    lines: list[str] = []
    lines.append("# Sentinel evaluation results")
    lines.append("")
    lines.append("> **Status:** PENDING — no real-provider run has been recorded yet.")
    lines.append(">")
    lines.append("> Per CLAUDE.md Golden Rule #5, no numerical metric ships in this")
    lines.append("> file until `make eval` has been executed against real `LLM_PROVIDER`")
    lines.append("> and `EMBEDDINGS_PROVIDER`. The metric definitions, dataset shape, and")
    lines.append("> provider/model slots below describe the harness contract; numbers")
    lines.append("> appear when a real run overwrites this file.")
    lines.append("")
    lines.append("All sample data is synthetic. See `docs/evaluation.md` for methodology.")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append("- **Run at (UTC):** _" + PENDING_HEADER + "_")
    lines.append("- **LLM provider:** _pending_ (target: `anthropic`)")
    lines.append("- **LLM model:** _pending_ (target: `claude-sonnet-4-6`)")
    lines.append("- **Embedding provider:** _pending_ (target: `openai`)")
    lines.append("- **Embedding model:** _pending_ (target: `text-embedding-3-small`)")
    lines.append("- **Embedding dim:** `1536`")
    lines.append("- **LLM temperature:** `0.0`")
    lines.append("- **Retrieval k:** `5`")
    lines.append("")
    lines.append("## Extraction (field-level accuracy)")
    lines.append("")
    lines.append("Metric definition: per-field exact-match after documented normalization")
    lines.append("(`eval/normalize.py`): trim + case-fold for strings, ISO canonicalisation")
    lines.append("for date strings, and a 0.01 absolute tolerance for numbers. Reports")
    lines.append("micro-accuracy (over all field slots), macro-accuracy (mean over per-field")
    lines.append("accuracies), per-field accuracy, and per-field precision/recall (which")
    lines.append("distinguishes wrong-value from missing-field for any optional/nullable")
    lines.append("field).")
    pending_extraction = [
        "",
        "- **Documents in dataset:** see `eval/labels/extraction_labels.json`",
        "- **Micro accuracy:** _" + PENDING_HEADER + "_",
        "- **Macro accuracy:** _" + PENDING_HEADER + "_",
        "- **Per-field accuracy / P / R:** _" + PENDING_HEADER + "_",
        "- **Failed extractions:** _" + PENDING_HEADER + "_",
    ]
    lines.extend(pending_extraction)
    lines.append("")
    lines.append("## Retrieval (precision@k, recall@k, MRR)")
    lines.append("")
    lines.append("Metric definitions:")
    lines.append("")
    lines.append("- `precision@k = |relevant ∩ top_k| / k`, averaged across queries.")
    lines.append("  Note: precision@k is structurally capped at `min(1, |relevant|/k)`,")
    lines.append("  so it reads pessimistic on queries where `|relevant| < k`. Reported as")
    lines.append("  the headline number with this footnote.")
    lines.append("- `recall@k = |relevant ∩ top_k| / |relevant|`, averaged.")
    lines.append("- `MRR = mean(1 / rank_of_first_relevant_in_top_k)`; `0` if no relevant")
    lines.append("  chunk appears in the top k for that query.")
    lines.append("")
    lines.append("- **Queries in dataset:** see `eval/labels/retrieval_labels.json`")
    lines.append("- **k:** `5`")
    lines.append("- **precision@k / recall@k / MRR:** _" + PENDING_HEADER + "_")
    lines.append("")
    lines.append("## RAG (citation-validity, answer cites relevant, lite faithfulness)")
    lines.append("")
    lines.append("Metric definitions:")
    lines.append("")
    lines.append("- **Citation-validity rate:** for each answered query, the fraction of")
    lines.append("  cited `[chunk:N]` ids that are present in the retrieved set; averaged.")
    lines.append("  Production code already enforces this (M3 invalid_citation refusal).")
    lines.append("  Reporting the rate here lets a regression in the prompt or LLM be")
    lines.append("  spotted before it triggers user-visible refusals.")
    lines.append("- **Answer-cites-relevant rate:** fraction of answered queries whose")
    lines.append("  cited chunks intersect the labeled-relevant set. Lite faithfulness")
    lines.append("  proxy without an LLM judge.")
    lines.append("- **Answer-substring match rate:** fraction of answers containing the")
    lines.append("  expected substring (case-insensitive). Sanity check; not faithfulness.")
    lines.append("- **Refusal rate:** fraction of questions where the M3 citation-or-refuse")
    lines.append("  policy refused. Reported but not interpreted as quality.")
    lines.append("")
    lines.append("- **Questions in dataset:** see `eval/labels/rag_labels.json`")
    lines.append(
        "- **Citation-validity / cites-relevant / substring / refusals:** _" + PENDING_HEADER + "_"
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "Per CLAUDE.md Golden Rule #5, this file reports **only real numbers** from "
        "a real-provider run. Sections marked `_pending_` are intentional placeholders "
        "and must not be misread as zero-valued metrics."
    )
    lines.append("")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _render_extraction(r: ExtractionResult) -> list[str]:
    out = ["## Extraction (field-level accuracy)", ""]
    out.append(f"- **Documents in dataset:** {r.n_documents}")
    out.append(f"- **Failed extractions:** {r.failed_extractions}")
    if not r.quotable:
        out.append(f"- **Status:** {r.note or 'n/a'}")
        return out
    out.append(f"- **Micro accuracy:** {_fmt(r.micro_accuracy)}")
    out.append(f"- **Macro accuracy:** {_fmt(r.macro_accuracy)}")
    out.append("")
    out.append("Per-field accuracy / precision / recall:")
    out.append("")
    out.append("| Field | Accuracy | Precision | Recall |")
    out.append("|---|---:|---:|---:|")
    for name, acc in sorted(r.per_field_accuracy.items()):
        pr = r.per_field_precision_recall.get(name, {})
        out.append(
            f"| `{name}` | {acc:.3f} | "
            f"{pr.get('precision', 0.0):.3f} | "
            f"{pr.get('recall', 0.0):.3f} |"
        )
    return out


def _render_retrieval(r: RetrievalResult) -> list[str]:
    out = ["## Retrieval (precision@k, recall@k, MRR)", ""]
    out.append(f"- **Queries scored:** {r.n_queries}")
    out.append(f"- **k:** {r.k}")
    if not r.quotable:
        out.append(f"- **Status:** {r.note or 'n/a'}")
        return out
    out.append(
        f"- **precision@{r.k}:** {_fmt(r.precision_at_k)} (capped below 1.0 when |relevant| < k)"
    )
    out.append(f"- **recall@{r.k}:** {_fmt(r.recall_at_k)}")
    out.append(f"- **MRR:** {_fmt(r.mrr)}")
    return out


def _render_rag(r: RagResult) -> list[str]:
    out = ["## RAG (citation-validity, answer cites relevant, lite faithfulness)", ""]
    out.append(f"- **Questions in dataset:** {r.n_questions}")
    out.append(f"- **Refusals:** {r.refusals}")
    out.append(f"- **Answered:** {r.answered}")
    if not r.quotable:
        out.append(f"- **Status:** {r.note or 'n/a'}")
        return out
    out.append(f"- **Citation-validity rate:** {_fmt(r.citation_validity_rate)}")
    out.append(f"- **Answer-cites-relevant rate:** {_fmt(r.cites_relevant_rate)}")
    out.append(f"- **Answer-substring match rate:** {_fmt(r.answer_substring_match_rate)}")
    return out


def report_to_dict(report: HarnessReport) -> dict[str, Any]:
    """For tests that want to assert against a structured form."""
    return {
        "extraction": asdict(report.extraction),
        "retrieval": asdict(report.retrieval),
        "rag": asdict(report.rag),
        "settings": report.settings_summary,
    }
