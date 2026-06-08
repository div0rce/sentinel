"""Eval harness.

Three evaluators, each independently runnable, and a :func:`run_all` orchestrator
that stitches their results into a single report. Each evaluator returns a
typed, frozen dataclass that the writer in :mod:`eval.results` can render.

Every evaluator takes a session and an :class:`EvalContext` (the shared
configuration, embedder, optional LLM, and corpus/label directories). The
per-item scoring lives in small mutable tally objects whose ``to_result`` method
emits the frozen result dataclass — this keeps each evaluator short and its
control flow shallow.

Honesty discipline (per CLAUDE.md Golden Rule #5 + the M9 design lock-in):

* If ``settings.embeddings_provider == "fake"`` the retrieval and citation-mapping
  primitives are non-semantic; :func:`evaluate_retrieval` and the
  citation-validity / lite-faithfulness arms of :func:`evaluate_rag` set
  ``quotable=False`` and emit ``None`` for every numerical metric.
* If ``settings.llm_provider == "fake"`` the extraction outputs aren't real
  predictions; :func:`evaluate_extraction` (and the answer-cites-relevant arm of
  :func:`evaluate_rag`) set ``quotable=False`` and emit ``None``.
* Counts (n_documents, n_queries, n_questions, refusals, etc.) are *always*
  emitted because they describe the dataset and the harness's own behaviour,
  not the system's quality.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.embeddings import EmbeddingProvider, get_embedder
from backend.app.extract import extract_document
from backend.app.ingest import canonical_hash, ingest_document
from backend.app.llm import LLMClient, get_llm
from backend.app.rag import answer_query
from backend.app.repositories import chunks as chunks_repo
from backend.app.repositories import documents as documents_repo
from eval.normalize import values_equal

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_DIR = Path(__file__).resolve().parent / "labels"
DEFAULT_CORPUS_DIR = REPO_ROOT / "data" / "sample"

CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]")


# --- result dataclasses ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Scored extraction metrics, or an n/a result (``quotable=False``) when the
    LLM provider is fake or no extraction succeeded."""

    n_documents: int
    quotable: bool
    micro_accuracy: float | None = None
    macro_accuracy: float | None = None
    per_field_accuracy: dict[str, float] = field(default_factory=dict)
    per_field_precision_recall: dict[str, dict[str, float]] = field(default_factory=dict)
    failed_extractions: int = 0
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Scored retrieval metrics (precision@k / recall@k / MRR), or an n/a result
    (``quotable=False``) under the fake embedder or when no query resolved.

    When ``quotable``, ``n_queries`` is the number of queries actually *scored* —
    label queries whose relevant chunks don't resolve are skipped and excluded from
    the averages. The n/a result reports the total label-set query count instead."""

    n_queries: int
    k: int
    quotable: bool
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    mrr: float | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RagResult:
    """Scored RAG metrics (citation-validity / cites-relevant / substring-match
    rates), or an n/a result (``quotable=False``) under a fake provider or when
    every question was refused."""

    n_questions: int
    refusals: int
    answered: int
    quotable: bool
    citation_validity_rate: float | None = None
    cites_relevant_rate: float | None = None
    answer_substring_match_rate: float | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessReport:
    """The combined output of all three evaluators plus the run's settings summary,
    consumed by :mod:`eval.results` to render ``RESULTS.md``."""

    extraction: ExtractionResult
    retrieval: RetrievalResult
    rag: RagResult
    settings_summary: dict[str, Any]


# --- evaluation context ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvalContext:
    """The shared dependencies every evaluator needs.

    Bundling configuration, the embedder, the (optional) LLM, and the
    corpus/label directories into one value keeps each evaluator's signature to
    ``(session, ctx)`` and puts the dependency wiring in a single place.
    """

    settings: Settings
    embedder: EmbeddingProvider
    llm: LLMClient | None = None
    corpus_dir: Path = DEFAULT_CORPUS_DIR
    labels_dir: Path = LABELS_DIR

    @classmethod
    def create(cls, settings: Settings | None = None) -> EvalContext:
        """Build a context for a production run, resolving ``settings`` and the
        ``embedder`` from the environment. The LLM is left lazy (see
        :meth:`require_llm`) so a retrieval-only run never forces an LLM provider to
        resolve — matching the original per-evaluator resolution behaviour. To inject
        fakes or point at a custom corpus/label dir (as the tests do), construct
        :class:`EvalContext` directly."""
        settings = settings or get_settings()
        return cls(settings=settings, embedder=get_embedder(settings))

    def require_llm(self) -> LLMClient:
        """Return the LLM if set, otherwise resolve one from settings.

        Does not cache the result (this is a frozen dataclass), so callers should
        bind the returned client to a local if they use it more than once.
        Evaluators that never call this (e.g. retrieval) never force an LLM provider
        to resolve."""
        return self.llm if self.llm is not None else get_llm(self.settings)


# --- corpus / label helpers --------------------------------------------------------


def _read_corpus_file(corpus_dir: Path, source_filename: str) -> str:
    """Read a corpus file's text by name, relative to ``corpus_dir``."""
    return (corpus_dir / source_filename).read_text(encoding="utf-8")


def _load_labels(name: str, labels_dir: Path) -> dict[str, Any]:
    """Load a label set from JSON, requiring a top-level object."""
    data = json.loads((labels_dir / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"label file {name!r} must contain a JSON object at top level")
    return data


def _ensure_ingested(session: Session, ctx: EvalContext, source_filename: str) -> int | None:
    """Ensure the labelled corpus file is ingested. Returns the document id, or
    ``None`` if the file is missing on disk."""
    path = ctx.corpus_dir / source_filename
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    existing = documents_repo.get_by_hash(session, canonical_hash(text))
    if existing is not None:
        return existing.id
    result = ingest_document(
        session,
        text=text,
        source=str(path.resolve()),
        title=path.stem,
        mime_type="text/markdown",
        embedder=ctx.embedder,
        settings=ctx.settings,
    )
    return result.document_id


def _ingest_relevant_sources(
    session: Session, ctx: EvalContext, entries: list[dict[str, Any]]
) -> None:
    """Ingest every corpus file referenced by any entry's ``relevant`` list."""
    referenced = {rel["source_filename"] for e in entries for rel in e.get("relevant", [])}
    for source in referenced:
        _ensure_ingested(session, ctx, source)


def _resolve_chunk_id(
    session: Session, ctx: EvalContext, source_filename: str, chunk_ord: int
) -> int | None:
    """Resolve the chunk id for a ``(source file, chunk ord)`` pair, or ``None``."""
    text = _read_corpus_file(ctx.corpus_dir, source_filename)
    doc = documents_repo.get_by_hash(session, canonical_hash(text))
    if doc is None:
        return None
    for chunk in chunks_repo.list_for_document(session, doc.id):
        if chunk.ord == chunk_ord:
            return chunk.id
    return None


def _resolve_relevant_ids(session: Session, ctx: EvalContext, entry: dict[str, Any]) -> set[int]:
    """Resolve the chunk ids of an entry's labelled-relevant references that exist."""
    ids: set[int] = set()
    for ref in entry.get("relevant", []):
        cid = _resolve_chunk_id(session, ctx, ref["source_filename"], ref["chunk_ord"])
        if cid is not None:
            ids.add(cid)
    return ids


# --- extraction --------------------------------------------------------------------


@dataclass
class _ExtractionTally:
    """Mutable accumulator for per-document extraction scoring."""

    field_correct: dict[str, int] = field(default_factory=dict)
    field_total: dict[str, int] = field(default_factory=dict)
    present_in_extraction: dict[str, int] = field(default_factory=dict)
    present_in_truth: dict[str, int] = field(default_factory=dict)
    correct_documents: int = 0
    total_documents: int = 0

    def score_document(self, expected: dict[str, Any], actual: dict[str, Any]) -> None:
        """Fold one successful extraction's per-field correctness into the tally."""
        self.total_documents += 1
        all_match = True
        for fname, expected_value in expected.items():
            self.field_total[fname] = self.field_total.get(fname, 0) + 1
            if expected_value is not None:
                self.present_in_truth[fname] = self.present_in_truth.get(fname, 0) + 1
            actual_value = actual.get(fname)
            if actual_value is not None:
                self.present_in_extraction[fname] = self.present_in_extraction.get(fname, 0) + 1
            if values_equal(expected_value, actual_value):
                self.field_correct[fname] = self.field_correct.get(fname, 0) + 1
            else:
                all_match = False
        if all_match:
            self.correct_documents += 1

    def to_result(self, *, n_documents: int, failed: int) -> ExtractionResult:
        """Emit the frozen result: micro/macro accuracy and per-field accuracy + P/R."""
        if self.total_documents == 0:
            return ExtractionResult(
                n_documents=n_documents,
                quotable=False,
                failed_extractions=failed,
                note="No extractions succeeded; cannot compute accuracy.",
            )
        micro_total = sum(self.field_total.values())
        micro_correct = sum(self.field_correct.values())
        micro_accuracy = micro_correct / micro_total if micro_total else 0.0

        per_field_accuracy = {
            name: self.field_correct.get(name, 0) / total
            for name, total in self.field_total.items()
            if total > 0
        }
        macro_accuracy = (
            sum(per_field_accuracy.values()) / len(per_field_accuracy)
            if per_field_accuracy
            else 0.0
        )

        per_field_pr: dict[str, dict[str, float]] = {}
        for name in self.field_total:
            correct = self.field_correct.get(name, 0)
            ex_present = self.present_in_extraction.get(name, 0)
            truth_present = self.present_in_truth.get(name, 0)
            per_field_pr[name] = {
                "precision": (correct / ex_present) if ex_present else 0.0,
                "recall": (correct / truth_present) if truth_present else 0.0,
            }

        return ExtractionResult(
            n_documents=n_documents,
            quotable=True,
            micro_accuracy=micro_accuracy,
            macro_accuracy=macro_accuracy,
            per_field_accuracy=per_field_accuracy,
            per_field_precision_recall=per_field_pr,
            failed_extractions=failed,
        )


def evaluate_extraction(session: Session, ctx: EvalContext) -> ExtractionResult:
    """Score schema extraction against the labelled corpus."""
    labels = _load_labels("extraction_labels.json", ctx.labels_dir)
    items: list[dict[str, Any]] = labels.get("items", [])
    n_documents = len(items)

    if ctx.settings.llm_provider == "fake":
        return ExtractionResult(
            n_documents=n_documents,
            quotable=False,
            note=(
                "n/a (LLM_PROVIDER=fake — non-quotable). The harness ran the extraction "
                "code path but did not call a real LLM; numbers are not published."
            ),
        )

    llm = ctx.require_llm()
    tally = _ExtractionTally()
    failed = 0
    for item in items:
        doc_id = _ensure_ingested(session, ctx, item["source_filename"])
        if doc_id is None:
            failed += 1
            continue
        result = extract_document(
            session,
            document_id=doc_id,
            schema_name=item["schema_name"],
            llm=llm,
            settings=ctx.settings,
        )
        if result.status != "ok":
            failed += 1
            continue
        tally.score_document(item["expected"], result.payload)

    return tally.to_result(n_documents=n_documents, failed=failed)


# --- retrieval ---------------------------------------------------------------------


@dataclass
class _RetrievalTally:
    """Mutable accumulator for per-query retrieval scoring."""

    precision_sum: float = 0.0
    recall_sum: float = 0.0
    rr_sum: float = 0.0
    valid_queries: int = 0

    def record(self, relevant_ids: set[int], retrieved_ids: list[int], k: int) -> None:
        """Fold one query's precision@k, recall@k, and reciprocal rank into the tally."""
        self.valid_queries += 1
        overlap = len(relevant_ids & set(retrieved_ids))
        self.precision_sum += overlap / k
        self.recall_sum += overlap / len(relevant_ids)
        rank = next((i + 1 for i, cid in enumerate(retrieved_ids) if cid in relevant_ids), 0)
        self.rr_sum += (1.0 / rank) if rank > 0 else 0.0

    def to_result(self, *, n_queries: int, k: int) -> RetrievalResult:
        """Emit the frozen result: mean precision@k, recall@k, and MRR."""
        if self.valid_queries == 0:
            return RetrievalResult(
                n_queries=n_queries,
                k=k,
                quotable=False,
                note="No queries had resolvable relevant chunks.",
            )
        return RetrievalResult(
            n_queries=self.valid_queries,
            k=k,
            quotable=True,
            precision_at_k=self.precision_sum / self.valid_queries,
            recall_at_k=self.recall_sum / self.valid_queries,
            mrr=self.rr_sum / self.valid_queries,
        )


def evaluate_retrieval(session: Session, ctx: EvalContext) -> RetrievalResult:
    """Score pgvector retrieval (precision@k / recall@k / MRR) against the labels."""
    labels = _load_labels("retrieval_labels.json", ctx.labels_dir)
    queries: list[dict[str, Any]] = labels.get("queries", [])
    k = int(labels.get("k", ctx.settings.retrieval_top_k))
    n_queries = len(queries)

    if ctx.settings.embeddings_provider == "fake":
        return RetrievalResult(
            n_queries=n_queries,
            k=k,
            quotable=False,
            note=(
                "n/a (EMBEDDINGS_PROVIDER=fake — FakeEmbedder is non-semantic; "
                "ranking is undefined for this purpose)."
            ),
        )

    # Lazy import here so the harness module imports cleanly when retrieval isn't run.
    from backend.app.retrieval import cosine_top_k

    _ingest_relevant_sources(session, ctx, queries)

    tally = _RetrievalTally()
    for entry in queries:
        relevant_ids = _resolve_relevant_ids(session, ctx, entry)
        if not relevant_ids:
            continue
        [query_vec] = ctx.embedder.embed([entry["query"]])
        hits = cosine_top_k(session, query_vec=query_vec, k=k)
        tally.record(relevant_ids, [h.chunk.id for h in hits], k)

    return tally.to_result(n_queries=n_queries, k=k)


# --- rag ---------------------------------------------------------------------------


def _parse_cited_chunk_ids(text: str) -> set[int]:
    """Return the chunk ids cited as ``[chunk:N]`` markers in ``text``."""
    return {int(m.group(1)) for m in CITATION_PATTERN.finditer(text)}


def _citation_validity_contribution(
    cited_ids: set[int], retrieved_ids: set[int]
) -> tuple[int, int]:
    """Return ``(hits, total)`` for one answer's citation-validity score.

    Every cited id should be in the retrieved set. An answer with no citations
    counts as 0/1 to penalise it — this mirrors the M3 citation-or-refuse posture
    while reporting a rate rather than refusing."""
    total = len(cited_ids) if cited_ids else 1
    if not cited_ids:
        return 0, total
    if cited_ids.issubset(retrieved_ids):
        return len(cited_ids), total
    return len(cited_ids & retrieved_ids), total


@dataclass
class _RagTally:
    """Mutable accumulator for per-question RAG scoring."""

    refusals: int = 0
    answered: int = 0
    citation_validity_hits: int = 0
    citation_validity_total: int = 0
    cites_relevant_hits: int = 0
    answer_substring_hits: int = 0

    def record_answer(
        self,
        *,
        answer: str,
        retrieved_ids: set[int],
        relevant_ids: set[int],
        expected_substring: str | None,
    ) -> None:
        """Fold one answered question into the citation-validity, cites-relevant,
        and substring-match arms."""
        self.answered += 1
        cited_ids = _parse_cited_chunk_ids(answer)
        hits, total = _citation_validity_contribution(cited_ids, retrieved_ids)
        self.citation_validity_hits += hits
        self.citation_validity_total += total
        if cited_ids & relevant_ids:
            self.cites_relevant_hits += 1
        if expected_substring and expected_substring.casefold() in answer.casefold():
            self.answer_substring_hits += 1

    def to_result(self, *, n_questions: int) -> RagResult:
        """Emit the frozen result: citation-validity, cites-relevant, substring rates."""
        if self.answered == 0:
            return RagResult(
                n_questions=n_questions,
                refusals=self.refusals,
                answered=0,
                quotable=False,
                note="All questions were refused; cannot compute answer-side metrics.",
            )
        citation_validity_rate = (
            self.citation_validity_hits / self.citation_validity_total
            if self.citation_validity_total
            else 0.0
        )
        return RagResult(
            n_questions=n_questions,
            refusals=self.refusals,
            answered=self.answered,
            quotable=True,
            citation_validity_rate=citation_validity_rate,
            cites_relevant_rate=self.cites_relevant_hits / self.answered,
            answer_substring_match_rate=self.answer_substring_hits / self.answered,
        )


def evaluate_rag(session: Session, ctx: EvalContext) -> RagResult:
    """Score citation-grounded RAG answers against the labelled questions."""
    labels = _load_labels("rag_labels.json", ctx.labels_dir)
    questions: list[dict[str, Any]] = labels.get("questions", [])
    n_questions = len(questions)

    if ctx.settings.embeddings_provider == "fake" or ctx.settings.llm_provider == "fake":
        return RagResult(
            n_questions=n_questions,
            refusals=0,
            answered=0,
            quotable=False,
            note=(
                "n/a (fake provider — citation-validity and answer-cites-relevant "
                "depend on real retrieval and a real LLM)."
            ),
        )

    llm = ctx.require_llm()
    _ingest_relevant_sources(session, ctx, questions)

    tally = _RagTally()
    for entry in questions:
        result = answer_query(
            session,
            query=entry["question"],
            embedder=ctx.embedder,
            llm=llm,
            settings=ctx.settings,
        )
        if result.status == "refused":
            tally.refusals += 1
            continue
        tally.record_answer(
            answer=result.answer,
            retrieved_ids={h.chunk.id for h in result.retrieved},
            relevant_ids=_resolve_relevant_ids(session, ctx, entry),
            expected_substring=entry.get("expected_answer_substring"),
        )

    return tally.to_result(n_questions=n_questions)


# --- orchestrator ------------------------------------------------------------------


def _settings_summary(settings: Settings) -> dict[str, Any]:
    """Snapshot the run's provider / model / threshold settings for RESULTS.md."""
    # Report the *active* provider's model, not a hardcoded Anthropic/OpenAI label, so
    # a Gemini (or fake) run does not mislabel itself in RESULTS.md (Golden Rule #5).
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.active_llm_model,
        "embeddings_provider": settings.embeddings_provider,
        "embedding_model": settings.active_embedding_model,
        "embedding_dim": settings.embedding_dim,
        "llm_temperature": settings.llm_temperature,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_score": settings.retrieval_min_score,
    }


def run_all(session: Session, ctx: EvalContext) -> HarnessReport:
    """Run every evaluator against ``ctx`` and assemble the combined report."""
    return HarnessReport(
        extraction=evaluate_extraction(session, ctx),
        retrieval=evaluate_retrieval(session, ctx),
        rag=evaluate_rag(session, ctx),
        settings_summary=_settings_summary(ctx.settings),
    )


def referenced_files(labels_dir: Path = LABELS_DIR) -> Iterable[str]:
    """Convenience: list every corpus file referenced by any label set. Useful for
    documenting the dataset shape in :file:`docs/evaluation.md`."""
    paths: set[str] = set()
    for name in (
        "extraction_labels.json",
        "retrieval_labels.json",
        "rag_labels.json",
    ):
        paths.update(_collect_filenames(_load_labels(name, labels_dir)))
    return sorted(paths)


def _collect_filenames(labels: dict[str, Any]) -> Sequence[str]:
    """Return every ``source_filename`` referenced in a single label set."""
    items = [e["source_filename"] for e in labels.get("items", []) if "source_filename" in e]
    relevant = [
        rel["source_filename"]
        for entry in labels.get("queries", []) + labels.get("questions", [])
        for rel in entry.get("relevant", [])
        if "source_filename" in rel
    ]
    return items + relevant
