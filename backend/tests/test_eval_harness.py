"""Tests for the M9 evaluation harness.

The user-facing eval contract is "the harness reports honest numbers". Proving
that contract end-to-end in pytest is the M9 keystone deliverable: scripted
fixtures + asserted expected metric values. These tests are *not* quality
claims — they prove the scorer and writer work.

Coverage:

* `evaluate_extraction` against a 1-document fixture, with a
  :class:`ScriptedFakeLLM` returning either a perfect JSON or a wrong-field
  JSON. Asserted micro/macro accuracy, per-field accuracy, per-field P/R, and
  the failed-extraction count.
* `evaluate_retrieval` against a 3-chunk fixture with a deterministic embedder
  that pins ranking exactly. Asserted precision@k, recall@k, and MRR.
* `evaluate_rag` against a 1-question fixture covering the citation-validity,
  cites-relevant, and substring-match arms.
* The honesty gate: every evaluator returns ``quotable=False`` and ``None``
  metrics when its provider is set to ``"fake"``.
* `render` and `render_pending` writers — round-trip body inspection.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.embeddings import FakeEmbedder
from backend.app.llm import LLMResponse
from backend.app.models import SCHEMA_EMBEDDING_DIM
from eval.harness import (
    HarnessReport,
    RagResult,
    RetrievalResult,
    evaluate_extraction,
    evaluate_rag,
    evaluate_retrieval,
)
from eval.results import render, render_pending

# --- scripted fakes ---------------------------------------------------------------


@dataclass
class ScriptedFakeLLM:
    """LLMClient stub. ``response_for_chunk`` (a function of the first
    ``[chunk:N]`` id seen in the user prompt) takes precedence over ``default``
    so tests can produce an answer that references the runtime-allocated chunk id."""

    default: str = ""
    response_for_chunk: Callable[[int], str] | None = None
    model_name: str = "scripted-fake"
    calls: int = field(default=0, init=False)

    def complete(
        self, *, system: str, user: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        self.calls += 1
        match = re.search(r"\[chunk:(\d+)\]", user)
        text: str
        if match is not None and self.response_for_chunk is not None:
            text = self.response_for_chunk(int(match.group(1)))
        else:
            text = self.default
        return LLMResponse(text=text, model=self.model_name, stop_reason="end_turn")


class _RankedEmbedder:
    """Deterministic embedder that returns crafted unit vectors keyed off the
    input text. Pins cosine similarity rankings for the retrieval/RAG tests."""

    def __init__(self, mapping: dict[str, list[float]], default: list[float] | None = None) -> None:
        self._mapping = mapping
        self._default = default or _basis(0)

    @property
    def dim(self) -> int:
        return SCHEMA_EMBEDDING_DIM

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            matched = self._default
            for needle, vec in self._mapping.items():
                if needle in text:
                    matched = vec
                    break
            out.append(matched)
        return out


def _basis(i: int, dim: int = SCHEMA_EMBEDDING_DIM) -> list[float]:
    v = [0.0] * dim
    v[i] = 1.0
    return v


def _unit(strength: float, dim: int = SCHEMA_EMBEDDING_DIM) -> list[float]:
    """Unit vector whose first component is ``strength``; remaining mass on
    component 1 to keep ``||v|| = 1``."""
    v = [0.0] * dim
    v[0] = strength
    v[1] = math.sqrt(max(0.0, 1.0 - strength * strength))
    return v


# --- corpus & label-file builders -------------------------------------------------


def _write_corpus(tmp_path: Path, files: dict[str, str]) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, body in files.items():
        (corpus / name).write_text(body, encoding="utf-8")
    return corpus


def _write_labels(tmp_path: Path, name: str, content: dict[str, Any]) -> Path:
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    (labels / name).write_text(json.dumps(content), encoding="utf-8")
    return labels


def _real_provider_settings(**overrides: Any) -> Settings:
    """Settings shape that bypasses the n/a gate. Tests inject scripted fakes via
    explicit ``llm=`` and ``embedder=`` arguments; the gate only consults
    ``settings.*_provider``, so reporting "anthropic"/"openai" here is the right
    posture: the test's *own* setup proves the scorer works on real-shaped
    inputs without making a real API call."""
    base: dict[str, Any] = {
        "llm_provider": "anthropic",
        "embeddings_provider": "openai",
        "llm_temperature": 0.0,
        "retrieval_top_k": 5,
        "retrieval_min_score": 0.0,
    }
    base.update(overrides)
    return Settings.model_validate(base)


# --- the n/a gate ----------------------------------------------------------------


def test_evaluate_extraction_emits_na_under_fake_llm(session: Session, tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path, {"a.md": "Anything"})
    labels = _write_labels(
        tmp_path,
        "extraction_labels.json",
        {
            "items": [
                {
                    "source_filename": "a.md",
                    "schema_name": "invoice",
                    "expected": {
                        "invoice_number": "I-1",
                        "vendor": "V",
                        "issue_date": "2026-01-01",
                        "total_due": 1.0,
                    },
                }
            ]
        },
    )
    result = evaluate_extraction(
        session,
        settings=Settings.model_validate({"llm_provider": "fake", "embeddings_provider": "fake"}),
        llm=ScriptedFakeLLM(),
        embedder=FakeEmbedder(),
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is False
    assert result.micro_accuracy is None
    assert result.macro_accuracy is None
    assert result.n_documents == 1
    assert "non-quotable" in (result.note or "")


def test_evaluate_retrieval_emits_na_under_fake_embedder(session: Session, tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path, {"a.md": "Anything"})
    labels = _write_labels(
        tmp_path,
        "retrieval_labels.json",
        {
            "k": 3,
            "queries": [
                {
                    "query": "anything",
                    "relevant": [{"source_filename": "a.md", "chunk_ord": 0}],
                }
            ],
        },
    )
    result = evaluate_retrieval(
        session,
        settings=Settings.model_validate({"embeddings_provider": "fake"}),
        embedder=FakeEmbedder(),
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is False
    assert result.precision_at_k is None
    assert result.recall_at_k is None
    assert result.mrr is None
    assert result.k == 3


def test_evaluate_rag_emits_na_under_either_fake(session: Session, tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path, {"a.md": "Anything"})
    labels = _write_labels(
        tmp_path,
        "rag_labels.json",
        {
            "questions": [
                {
                    "question": "anything?",
                    "relevant": [{"source_filename": "a.md", "chunk_ord": 0}],
                    "expected_answer_substring": "anything",
                }
            ]
        },
    )
    for settings in (
        Settings.model_validate({"llm_provider": "fake", "embeddings_provider": "openai"}),
        Settings.model_validate({"llm_provider": "anthropic", "embeddings_provider": "fake"}),
    ):
        result = evaluate_rag(
            session,
            settings=settings,
            llm=ScriptedFakeLLM(),
            embedder=FakeEmbedder(),
            corpus_dir=corpus,
            labels_dir=labels,
        )
        assert result.quotable is False
        assert result.citation_validity_rate is None
        assert result.cites_relevant_rate is None


# --- evaluate_extraction: asserted scorer behaviour -------------------------------


def _perfect_invoice_json_for(chunk_id: int) -> str:
    return json.dumps(
        {
            "invoice_number": {
                "value": "INV-X",
                "confidence": 0.95,
                "source_chunk_id": chunk_id,
            },
            "vendor": {"value": "Acme", "confidence": 0.95, "source_chunk_id": chunk_id},
            "issue_date": {
                "value": "2026-01-22",
                "confidence": 0.95,
                "source_chunk_id": chunk_id,
            },
            "total_due": {
                "value": 1234.56,
                "confidence": 0.95,
                "source_chunk_id": chunk_id,
            },
        }
    )


def _wrong_vendor_invoice_json_for(chunk_id: int) -> str:
    payload = json.loads(_perfect_invoice_json_for(chunk_id))
    payload["vendor"]["value"] = "WRONG"
    return json.dumps(payload)


def _expected_invoice_payload() -> dict[str, Any]:
    return {
        "invoice_number": "INV-X",
        "vendor": "Acme",
        "issue_date": "2026-01-22",
        "total_due": 1234.56,
    }


def test_evaluate_extraction_perfect_run_yields_unit_accuracy(
    session: Session, tmp_path: Path
) -> None:
    corpus = _write_corpus(tmp_path, {"x.md": "INV-X from Acme, 2026-01-22, total $1,234.56."})
    labels = _write_labels(
        tmp_path,
        "extraction_labels.json",
        {
            "items": [
                {
                    "source_filename": "x.md",
                    "schema_name": "invoice",
                    "expected": _expected_invoice_payload(),
                }
            ]
        },
    )
    llm = ScriptedFakeLLM(response_for_chunk=_perfect_invoice_json_for)

    result = evaluate_extraction(
        session,
        settings=_real_provider_settings(),
        llm=llm,
        embedder=FakeEmbedder(),
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is True
    assert result.failed_extractions == 0
    assert result.micro_accuracy == pytest.approx(1.0)
    assert result.macro_accuracy == pytest.approx(1.0)
    for name in ("invoice_number", "vendor", "issue_date", "total_due"):
        assert result.per_field_accuracy[name] == pytest.approx(1.0)
        assert result.per_field_precision_recall[name]["precision"] == pytest.approx(1.0)
        assert result.per_field_precision_recall[name]["recall"] == pytest.approx(1.0)


def test_evaluate_extraction_one_wrong_field_pins_micro_macro(
    session: Session, tmp_path: Path
) -> None:
    """One document, one wrong field out of four → 3/4 = 0.75 on every meaningful axis."""
    corpus = _write_corpus(tmp_path, {"y.md": "INV-Y from Acme, 2026-01-22, total $1,234.56."})
    labels = _write_labels(
        tmp_path,
        "extraction_labels.json",
        {
            "items": [
                {
                    "source_filename": "y.md",
                    "schema_name": "invoice",
                    "expected": _expected_invoice_payload(),
                }
            ]
        },
    )
    llm = ScriptedFakeLLM(response_for_chunk=_wrong_vendor_invoice_json_for)

    result = evaluate_extraction(
        session,
        settings=_real_provider_settings(),
        llm=llm,
        embedder=FakeEmbedder(),
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is True
    assert result.failed_extractions == 0
    # 3 of 4 fields correct → micro = 0.75. Macro = mean of (1, 0, 1, 1) = 0.75.
    assert result.micro_accuracy == pytest.approx(0.75)
    assert result.macro_accuracy == pytest.approx(0.75)
    assert result.per_field_accuracy["vendor"] == pytest.approx(0.0)
    assert result.per_field_accuracy["invoice_number"] == pytest.approx(1.0)
    # Per-field P/R for the wrong field: precision = correct / extracted = 0/1 = 0.
    assert result.per_field_precision_recall["vendor"]["precision"] == pytest.approx(0.0)
    assert result.per_field_precision_recall["vendor"]["recall"] == pytest.approx(0.0)


# --- evaluate_retrieval: asserted scorer behaviour --------------------------------


def test_evaluate_retrieval_pins_precision_recall_mrr(session: Session, tmp_path: Path) -> None:
    """Three chunks, each with a distinct unit vector. One labeled query whose
    relevant set is exactly the alpha chunk. With k=2, the embedder ranks alpha
    first → precision@2=0.5 (only one of the two retrieved is relevant),
    recall@2=1.0 (the only relevant chunk is in the top-2), MRR=1.0 (alpha at
    rank 1)."""
    chunk_a_text = "alpha document body talking about Acme"
    chunk_b_text = "beta document body talking about Initech"
    chunk_c_text = "gamma document body talking about Wayne"

    corpus = _write_corpus(
        tmp_path,
        {
            "alpha.md": chunk_a_text,
            "beta.md": chunk_b_text,
            "gamma.md": chunk_c_text,
        },
    )

    embedder = _RankedEmbedder(
        {
            "alpha": _unit(1.0),
            "beta": _unit(0.5),
            "gamma": _unit(0.1),
            "Acme": _unit(1.0),
        }
    )

    labels = _write_labels(
        tmp_path,
        "retrieval_labels.json",
        {
            "k": 2,
            "queries": [
                {
                    "query": "Acme",
                    "relevant": [{"source_filename": "alpha.md", "chunk_ord": 0}],
                }
            ],
        },
    )

    result = evaluate_retrieval(
        session,
        settings=_real_provider_settings(retrieval_top_k=2),
        embedder=embedder,
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is True
    assert result.k == 2
    assert result.precision_at_k == pytest.approx(0.5)
    assert result.recall_at_k == pytest.approx(1.0)
    assert result.mrr == pytest.approx(1.0)


# --- evaluate_rag: asserted scorer behaviour --------------------------------------


def test_evaluate_rag_pins_three_rates_on_happy_path(session: Session, tmp_path: Path) -> None:
    """Single question, single chunk; the LLM cites that chunk and includes the
    expected substring → all three rates = 1.0."""
    chunk_text = "The total due on the Initech Components invoice is 90,006.92 dollars."
    corpus = _write_corpus(tmp_path, {"a.md": chunk_text})

    embedder = _RankedEmbedder({"Initech": _unit(1.0)}, default=_unit(1.0))

    def respond(cid: int) -> str:
        return f"The total due is 90,006.92 dollars [chunk:{cid}]."

    llm = ScriptedFakeLLM(response_for_chunk=respond)

    labels = _write_labels(
        tmp_path,
        "rag_labels.json",
        {
            "questions": [
                {
                    "question": "What is the total due on the Initech invoice?",
                    "relevant": [{"source_filename": "a.md", "chunk_ord": 0}],
                    "expected_answer_substring": "90,006.92",
                }
            ]
        },
    )

    result = evaluate_rag(
        session,
        settings=_real_provider_settings(retrieval_top_k=3),
        llm=llm,
        embedder=embedder,
        corpus_dir=corpus,
        labels_dir=labels,
    )
    assert result.quotable is True
    assert result.refusals == 0
    assert result.answered == 1
    assert result.citation_validity_rate == pytest.approx(1.0)
    assert result.cites_relevant_rate == pytest.approx(1.0)
    assert result.answer_substring_match_rate == pytest.approx(1.0)


# --- writer round-trip ------------------------------------------------------------


def test_render_pending_contains_methodology_only_no_numbers() -> None:
    body = render_pending()
    assert "Numbers pending real-provider run" in body
    assert "claude-sonnet-4-6" in body
    assert "text-embedding-3-small" in body
    # No accidental numeric metric in the pending file.
    assert "| 0." not in body
    assert "1.000" not in body


def test_render_writes_real_metrics_when_quotable(session: Session, tmp_path: Path) -> None:
    """End-to-end: the perfect-extraction run feeds the writer, which renders
    the asserted accuracy lines into Markdown. Other arms are not-run / n/a."""
    corpus = _write_corpus(tmp_path, {"x.md": "INV-X from Acme, 2026-01-22, total $1,234.56."})
    labels = _write_labels(
        tmp_path,
        "extraction_labels.json",
        {
            "items": [
                {
                    "source_filename": "x.md",
                    "schema_name": "invoice",
                    "expected": _expected_invoice_payload(),
                }
            ]
        },
    )
    llm = ScriptedFakeLLM(response_for_chunk=_perfect_invoice_json_for)

    extraction = evaluate_extraction(
        session,
        settings=_real_provider_settings(),
        llm=llm,
        embedder=FakeEmbedder(),
        corpus_dir=corpus,
        labels_dir=labels,
    )

    report = HarnessReport(
        extraction=extraction,
        retrieval=RetrievalResult(n_queries=0, k=5, quotable=False, note="not run"),
        rag=RagResult(
            n_questions=0,
            refusals=0,
            answered=0,
            quotable=False,
            note="not run",
        ),
        settings_summary={
            "llm_provider": "anthropic",
            "claude_model": "claude-sonnet-4-6",
            "embeddings_provider": "openai",
            "openai_embedding_model": "text-embedding-3-small",
            "embedding_dim": SCHEMA_EMBEDDING_DIM,
            "llm_temperature": 0.0,
            "retrieval_top_k": 5,
            "retrieval_min_score": 0.0,
        },
    )
    body = render(report)
    assert "claude-sonnet-4-6" in body
    assert "**Micro accuracy:** 1.000" in body
    assert "**Macro accuracy:** 1.000" in body
    # Retrieval and RAG should clearly say not-run / n/a, not produce numbers.
    assert "not run" in body
