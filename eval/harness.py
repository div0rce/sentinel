"""Eval harness.

Three evaluators, each independently runnable, and a :func:`run_all` orchestrator
that stitches their results into a single report. Each evaluator returns a
typed, frozen dataclass that the writer in :mod:`eval.results` can render.

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
    n_queries: int
    k: int
    quotable: bool
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    mrr: float | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RagResult:
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
    extraction: ExtractionResult
    retrieval: RetrievalResult
    rag: RagResult
    settings_summary: dict[str, Any]


# --- helpers ----------------------------------------------------------------------


def _read_corpus_file(corpus_dir: Path, source_filename: str) -> str:
    path = corpus_dir / source_filename
    return path.read_text(encoding="utf-8")


def _ensure_ingested(
    session: Session,
    *,
    corpus_dir: Path,
    source_filename: str,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> int | None:
    """Ensure the labelled corpus file is ingested. Returns the document id or None
    if the file is missing on disk."""
    path = corpus_dir / source_filename
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    content_hash = canonical_hash(text)
    existing = documents_repo.get_by_hash(session, content_hash)
    if existing is not None:
        return existing.id
    result = ingest_document(
        session,
        text=text,
        source=str(path.resolve()),
        title=path.stem,
        mime_type="text/markdown",
        embedder=embedder,
        settings=settings,
    )
    return result.document_id


def _resolve_chunk_id(
    session: Session, *, corpus_dir: Path, source_filename: str, chunk_ord: int
) -> int | None:
    text = _read_corpus_file(corpus_dir, source_filename)
    doc = documents_repo.get_by_hash(session, canonical_hash(text))
    if doc is None:
        return None
    chunks = chunks_repo.list_for_document(session, doc.id)
    for chunk in chunks:
        if chunk.ord == chunk_ord:
            return chunk.id
    return None


def _load_labels(name: str, labels_dir: Path) -> dict[str, Any]:
    data = json.loads((labels_dir / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"label file {name!r} must contain a JSON object at top level")
    return data


# --- extraction --------------------------------------------------------------------


def evaluate_extraction(
    session: Session,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    embedder: EmbeddingProvider | None = None,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    labels_dir: Path = LABELS_DIR,
) -> ExtractionResult:
    settings = settings or get_settings()
    embedder = embedder or get_embedder(settings)
    llm = llm or get_llm(settings)

    labels = _load_labels("extraction_labels.json", labels_dir)
    items: list[dict[str, Any]] = labels.get("items", [])
    n_documents = len(items)

    if settings.llm_provider == "fake":
        return ExtractionResult(
            n_documents=n_documents,
            quotable=False,
            note=(
                "n/a (LLM_PROVIDER=fake — non-quotable). The harness ran the extraction "
                "code path but did not call a real LLM; numbers are not published."
            ),
        )

    field_correct: dict[str, int] = {}
    field_total: dict[str, int] = {}
    field_present_in_extraction: dict[str, int] = {}
    field_present_in_truth: dict[str, int] = {}
    correct_documents = 0
    total_documents = 0
    failed = 0

    for item in items:
        source = item["source_filename"]
        doc_id = _ensure_ingested(
            session,
            corpus_dir=corpus_dir,
            source_filename=source,
            embedder=embedder,
            settings=settings,
        )
        if doc_id is None:
            failed += 1
            continue
        result = extract_document(
            session,
            document_id=doc_id,
            schema_name=item["schema_name"],
            llm=llm,
            settings=settings,
        )
        if result.status != "ok":
            failed += 1
            continue
        total_documents += 1
        expected = item["expected"]
        actual = result.payload
        all_match = True
        for fname, expected_value in expected.items():
            field_total[fname] = field_total.get(fname, 0) + 1
            if expected_value is not None:
                field_present_in_truth[fname] = field_present_in_truth.get(fname, 0) + 1
            actual_value = actual.get(fname)
            if actual_value is not None:
                field_present_in_extraction[fname] = field_present_in_extraction.get(fname, 0) + 1
            if values_equal(expected_value, actual_value):
                field_correct[fname] = field_correct.get(fname, 0) + 1
            else:
                all_match = False
        if all_match:
            correct_documents += 1

    if total_documents == 0:
        return ExtractionResult(
            n_documents=n_documents,
            quotable=False,
            failed_extractions=failed,
            note="No extractions succeeded; cannot compute accuracy.",
        )

    micro_total = sum(field_total.values())
    micro_correct = sum(field_correct.values())
    micro_accuracy = micro_correct / micro_total if micro_total else 0.0

    per_field_accuracy = {
        name: (field_correct.get(name, 0) / total)
        for name, total in field_total.items()
        if total > 0
    }
    macro_accuracy = (
        sum(per_field_accuracy.values()) / len(per_field_accuracy) if per_field_accuracy else 0.0
    )

    per_field_pr: dict[str, dict[str, float]] = {}
    for name in field_total:
        truth_present = field_present_in_truth.get(name, 0)
        ex_present = field_present_in_extraction.get(name, 0)
        correct = field_correct.get(name, 0)
        precision = (correct / ex_present) if ex_present else 0.0
        recall = (correct / truth_present) if truth_present else 0.0
        per_field_pr[name] = {"precision": precision, "recall": recall}

    return ExtractionResult(
        n_documents=n_documents,
        quotable=True,
        micro_accuracy=micro_accuracy,
        macro_accuracy=macro_accuracy,
        per_field_accuracy=per_field_accuracy,
        per_field_precision_recall=per_field_pr,
        failed_extractions=failed,
    )


# --- retrieval ---------------------------------------------------------------------


def evaluate_retrieval(
    session: Session,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingProvider | None = None,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    labels_dir: Path = LABELS_DIR,
) -> RetrievalResult:
    settings = settings or get_settings()
    embedder = embedder or get_embedder(settings)

    labels = _load_labels("retrieval_labels.json", labels_dir)
    queries: list[dict[str, Any]] = labels.get("queries", [])
    k = int(labels.get("k", settings.retrieval_top_k))
    n_queries = len(queries)

    if settings.embeddings_provider == "fake":
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

    # Ensure every relevance-judged file is ingested.
    referenced: set[str] = {
        rel["source_filename"] for q in queries for rel in q.get("relevant", [])
    }
    for source in referenced:
        _ensure_ingested(
            session,
            corpus_dir=corpus_dir,
            source_filename=source,
            embedder=embedder,
            settings=settings,
        )

    precision_sum = 0.0
    recall_sum = 0.0
    rr_sum = 0.0
    valid_queries = 0

    for entry in queries:
        relevant_ids: set[int] = set()
        for ref in entry.get("relevant", []):
            cid = _resolve_chunk_id(
                session,
                corpus_dir=corpus_dir,
                source_filename=ref["source_filename"],
                chunk_ord=ref["chunk_ord"],
            )
            if cid is not None:
                relevant_ids.add(cid)
        if not relevant_ids:
            continue
        valid_queries += 1
        [query_vec] = embedder.embed([entry["query"]])
        hits = cosine_top_k(session, query_vec=query_vec, k=k)
        retrieved_ids = [h.chunk.id for h in hits]
        retrieved_set = set(retrieved_ids)

        precision_sum += len(relevant_ids & retrieved_set) / k
        recall_sum += len(relevant_ids & retrieved_set) / len(relevant_ids)

        rank = next(
            (i + 1 for i, cid in enumerate(retrieved_ids) if cid in relevant_ids),
            0,
        )
        rr_sum += (1.0 / rank) if rank > 0 else 0.0

    if valid_queries == 0:
        return RetrievalResult(
            n_queries=n_queries,
            k=k,
            quotable=False,
            note="No queries had resolvable relevant chunks.",
        )

    return RetrievalResult(
        n_queries=valid_queries,
        k=k,
        quotable=True,
        precision_at_k=precision_sum / valid_queries,
        recall_at_k=recall_sum / valid_queries,
        mrr=rr_sum / valid_queries,
    )


# --- rag --------------------------------------------------------------------------


def _parse_cited_chunk_ids(text: str) -> set[int]:
    return {int(m.group(1)) for m in CITATION_PATTERN.finditer(text)}


def evaluate_rag(
    session: Session,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    embedder: EmbeddingProvider | None = None,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    labels_dir: Path = LABELS_DIR,
) -> RagResult:
    settings = settings or get_settings()
    embedder = embedder or get_embedder(settings)
    llm = llm or get_llm(settings)

    labels = _load_labels("rag_labels.json", labels_dir)
    questions: list[dict[str, Any]] = labels.get("questions", [])
    n_questions = len(questions)

    if settings.embeddings_provider == "fake" or settings.llm_provider == "fake":
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

    referenced: set[str] = {
        rel["source_filename"] for q in questions for rel in q.get("relevant", [])
    }
    for source in referenced:
        _ensure_ingested(
            session,
            corpus_dir=corpus_dir,
            source_filename=source,
            embedder=embedder,
            settings=settings,
        )

    refusals = 0
    answered = 0
    citation_validity_hits = 0
    citation_validity_total = 0
    cites_relevant_hits = 0
    answer_substring_hits = 0

    for entry in questions:
        result = answer_query(
            session,
            query=entry["question"],
            embedder=embedder,
            llm=llm,
            settings=settings,
        )
        if result.status == "refused":
            refusals += 1
            continue
        answered += 1

        retrieved_ids = {h.chunk.id for h in result.retrieved}
        cited_ids = _parse_cited_chunk_ids(result.answer)
        citation_validity_total += len(cited_ids) if cited_ids else 1
        # Every cited id should be in the retrieved set; if no citations exist we
        # count as 0/1 to penalise a citation-less answer (this matches the M3
        # citation-or-refuse posture but reports the rate rather than refusing).
        if cited_ids and cited_ids.issubset(retrieved_ids):
            citation_validity_hits += len(cited_ids)
        elif cited_ids:
            citation_validity_hits += len(cited_ids & retrieved_ids)

        relevant_ids = {
            _resolve_chunk_id(
                session,
                corpus_dir=corpus_dir,
                source_filename=ref["source_filename"],
                chunk_ord=ref["chunk_ord"],
            )
            for ref in entry.get("relevant", [])
        }
        relevant_ids.discard(None)
        if cited_ids & relevant_ids:
            cites_relevant_hits += 1

        expected_substring = entry.get("expected_answer_substring")
        if expected_substring and expected_substring.casefold() in result.answer.casefold():
            answer_substring_hits += 1

    if answered == 0:
        return RagResult(
            n_questions=n_questions,
            refusals=refusals,
            answered=0,
            quotable=False,
            note="All questions were refused; cannot compute answer-side metrics.",
        )

    citation_validity_rate = (
        citation_validity_hits / citation_validity_total if citation_validity_total else 0.0
    )
    cites_relevant_rate = cites_relevant_hits / answered
    answer_substring_match_rate = answer_substring_hits / answered

    return RagResult(
        n_questions=n_questions,
        refusals=refusals,
        answered=answered,
        quotable=True,
        citation_validity_rate=citation_validity_rate,
        cites_relevant_rate=cites_relevant_rate,
        answer_substring_match_rate=answer_substring_match_rate,
    )


# --- orchestrator ------------------------------------------------------------------


def _settings_summary(settings: Settings) -> dict[str, Any]:
    return {
        "llm_provider": settings.llm_provider,
        "claude_model": settings.claude_model,
        "embeddings_provider": settings.embeddings_provider,
        "openai_embedding_model": settings.openai_embedding_model,
        "embedding_dim": settings.embedding_dim,
        "llm_temperature": settings.llm_temperature,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_score": settings.retrieval_min_score,
    }


def run_all(
    session: Session,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    embedder: EmbeddingProvider | None = None,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    labels_dir: Path = LABELS_DIR,
) -> HarnessReport:
    settings = settings or get_settings()

    extraction = evaluate_extraction(
        session,
        settings=settings,
        llm=llm,
        embedder=embedder,
        corpus_dir=corpus_dir,
        labels_dir=labels_dir,
    )
    retrieval = evaluate_retrieval(
        session,
        settings=settings,
        embedder=embedder,
        corpus_dir=corpus_dir,
        labels_dir=labels_dir,
    )
    rag = evaluate_rag(
        session,
        settings=settings,
        llm=llm,
        embedder=embedder,
        corpus_dir=corpus_dir,
        labels_dir=labels_dir,
    )

    return HarnessReport(
        extraction=extraction,
        retrieval=retrieval,
        rag=rag,
        settings_summary=_settings_summary(settings),
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
    out: list[str] = []
    for entry in labels.get("items", []):
        if "source_filename" in entry:
            out.append(entry["source_filename"])
    for entry in labels.get("queries", []) + labels.get("questions", []):
        for rel in entry.get("relevant", []):
            if "source_filename" in rel:
                out.append(rel["source_filename"])
    return out
