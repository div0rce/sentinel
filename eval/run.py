"""``python -m eval.run`` — entry point used by ``make eval``.

Opens a session against the configured DATABASE_URL, runs every evaluator,
prints a terse summary to stdout, and writes :file:`eval/RESULTS.md`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.config import get_settings
from backend.app.db import get_session_factory
from eval.harness import HarnessReport, run_all
from eval.results import render

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "eval" / "RESULTS.md"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m eval.run",
        description="Run the Sentinel evaluation harness and write eval/RESULTS.md.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS_PATH,
        help="Where to write the RESULTS.md file. Default: eval/RESULTS.md",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write RESULTS.md; only print the summary to stdout.",
    )
    return parser


def _print_summary(report: HarnessReport) -> None:
    s = report.settings_summary
    print(
        f"eval: llm={s['llm_provider']}/{s['claude_model']} "
        f"emb={s['embeddings_provider']}/{s['openai_embedding_model']} "
        f"temp={s['llm_temperature']} k={s['retrieval_top_k']}"
    )
    er = report.extraction
    rr = report.retrieval
    rg = report.rag
    print(
        "extraction: "
        + (
            f"micro={er.micro_accuracy:.3f} macro={er.macro_accuracy:.3f}"
            f" failed={er.failed_extractions}"
            if er.quotable and er.micro_accuracy is not None and er.macro_accuracy is not None
            else f"n/a (n_documents={er.n_documents}, failed={er.failed_extractions})"
        )
    )
    print(
        "retrieval:  "
        + (
            f"p@{rr.k}={rr.precision_at_k:.3f} r@{rr.k}={rr.recall_at_k:.3f} mrr={rr.mrr:.3f}"
            if rr.quotable
            and rr.precision_at_k is not None
            and rr.recall_at_k is not None
            and rr.mrr is not None
            else f"n/a (n_queries={rr.n_queries}, k={rr.k})"
        )
    )
    print(
        "rag:        "
        + (
            f"cite_valid={rg.citation_validity_rate:.3f} "
            f"cite_relevant={rg.cites_relevant_rate:.3f} "
            f"substr={rg.answer_substring_match_rate:.3f} "
            f"refusals={rg.refusals}/{rg.n_questions}"
            if rg.quotable
            and rg.citation_validity_rate is not None
            and rg.cites_relevant_rate is not None
            and rg.answer_substring_match_rate is not None
            else f"n/a (n_questions={rg.n_questions}, refusals={rg.refusals})"
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    factory = get_session_factory()
    with factory() as session:
        report = run_all(session, settings=settings)
        # The harness only reads; ensure no stray writes leak. Rolling back keeps
        # the eval idempotent against a long-lived DB.
        session.rollback()

    _print_summary(report)

    if not args.no_write:
        body = render(report)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        print(f"eval: wrote {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
