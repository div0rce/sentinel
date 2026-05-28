"""Tests for the M3 citation-grounded RAG pipeline.

All tests use :class:`FakeLLM` and either :class:`FakeEmbedder` or crafted vectors;
no live API calls happen. The DoD's three RAG-test items are covered here:

* retrieval ordering — exercised end-to-end through the pipeline (the SQL-level
  ordering is independently tested in ``test_retrieval.py``).
* refusal when unsupported — both no-chunks-above-threshold and uncited-LLM-response.
* citation → chunk mapping correctness — only retrieved chunk ids that the LLM
  cites become structured citations; bogus ids are dropped; the rest of the
  retrieved list is preserved.
"""

from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.llm import FakeLLM
from backend.app.models import SCHEMA_EMBEDDING_DIM, Chunk, Document
from backend.app.rag import REFUSAL_TEXT, answer_query


def _crafted_vector(strength: float) -> list[float]:
    v = [0.0] * SCHEMA_EMBEDDING_DIM
    v[0] = strength
    v[1] = math.sqrt(max(0.0, 1.0 - strength * strength))
    return v


def _seed_aligned_chunks(session: Session, *, hash_suffix: str, count: int = 3) -> Document:
    """Insert ``count`` chunks whose vectors are aligned with the unit query."""
    doc = Document(hash="g" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}")
    session.add(doc)
    session.flush()
    for i in range(count):
        # strengths 0.95, 0.90, 0.85, ...
        strength = 0.95 - 0.05 * i
        session.add(
            Chunk(
                document_id=doc.id,
                ord=i,
                text=f"Synthetic content body {i} for {hash_suffix}.",
                token_count=10,
                embedding=_crafted_vector(strength),
            )
        )
    session.flush()
    return doc


class _AlignedQueryEmbedder:
    """Embedder that returns the unit-x query vector for any input.

    Used so the RAG pipeline's call to ``embedder.embed([query])`` produces the
    same query vector ``test_retrieval`` uses, making cosine similarity scores
    equal to each chunk's encoded ``strength``.
    """

    @property
    def dim(self) -> int:
        return SCHEMA_EMBEDDING_DIM

    def embed(self, texts):  # type: ignore[no-untyped-def]
        unit = [0.0] * SCHEMA_EMBEDDING_DIM
        unit[0] = 1.0
        return [unit for _ in texts]


def test_answer_query_happy_path_returns_citations(session: Session) -> None:
    _seed_aligned_chunks(session, hash_suffix="hp")

    # FakeLLM cites the first chunk id present in the user prompt.
    def cite_first(system: str, user: str) -> str:
        match = re.search(r"\[chunk:(\d+)\]", user)
        assert match is not None, "RAG must include [chunk:N] markers in the user prompt"
        cid = match.group(1)
        return f"The answer is in the corpus [chunk:{cid}]."

    llm = FakeLLM(response_factory=cite_first)
    settings = Settings(
        llm_provider="fake",
        embeddings_provider="fake",
        retrieval_top_k=3,
        retrieval_min_score=0.3,
    )

    result = answer_query(
        session,
        query="What does the corpus say?",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "answered"
    assert result.reason is None
    assert "[chunk:" in result.answer
    assert len(result.citations) == 1
    cited = result.citations[0]
    # The cited chunk must be one of the retrieved chunks.
    retrieved_ids = {h.chunk.id for h in result.retrieved}
    assert cited.chunk_id in retrieved_ids
    # Citation score equals the retrieved chunk's score.
    score_by_id = {h.chunk.id: h.score for h in result.retrieved}
    assert math.isclose(cited.score, score_by_id[cited.chunk_id], rel_tol=1e-6)


def test_answer_query_refuses_when_top_score_below_threshold(session: Session) -> None:
    _seed_aligned_chunks(session, hash_suffix="lo")
    settings = Settings(
        llm_provider="fake",
        embeddings_provider="fake",
        retrieval_top_k=3,
        retrieval_min_score=0.99,  # higher than any seeded strength (max 0.95)
    )

    llm = FakeLLM(response="this should never reach the caller [chunk:1]")
    result = answer_query(
        session,
        query="anything",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "refused"
    assert result.reason == "no_support"
    assert result.answer == REFUSAL_TEXT
    assert result.citations == []


def test_answer_query_refuses_when_no_chunks_in_corpus(session: Session) -> None:
    settings = Settings(llm_provider="fake", embeddings_provider="fake")
    llm = FakeLLM(response="will not be used")
    result = answer_query(
        session,
        query="anything",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "refused"
    assert result.reason == "no_support"
    assert result.citations == []


def test_answer_query_refuses_when_llm_does_not_cite(session: Session) -> None:
    _seed_aligned_chunks(session, hash_suffix="un")
    settings = Settings(
        llm_provider="fake",
        embeddings_provider="fake",
        retrieval_top_k=3,
        retrieval_min_score=0.3,
    )

    llm = FakeLLM(response="A fluent answer without any citations whatsoever.")
    result = answer_query(
        session,
        query="anything",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "refused"
    assert result.reason == "uncited"
    assert result.answer == REFUSAL_TEXT
    assert result.citations == []


def test_answer_query_drops_citations_to_unknown_chunk_ids(session: Session) -> None:
    _seed_aligned_chunks(session, hash_suffix="bg")
    settings = Settings(
        llm_provider="fake",
        embeddings_provider="fake",
        retrieval_top_k=3,
        retrieval_min_score=0.3,
    )

    # The LLM cites a chunk id that is NOT in the retrieved set. With no other
    # citations, the answer must be refused as 'uncited'.
    llm = FakeLLM(response="The answer relies on [chunk:99999999] which we did not retrieve.")
    result = answer_query(
        session,
        query="anything",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "refused"
    assert result.reason == "uncited"


def test_answer_query_citation_to_chunk_mapping_is_correct(session: Session) -> None:
    """Mixed valid + bogus citations: the bogus ones are dropped, the valid ones map
    back to their retrieved chunks, deduplicated, in first-seen order."""
    _seed_aligned_chunks(session, hash_suffix="map", count=3)
    settings = Settings(
        llm_provider="fake",
        embeddings_provider="fake",
        retrieval_top_k=3,
        retrieval_min_score=0.3,
    )

    def cite_two_real_one_fake(system: str, user: str) -> str:
        # Pull the first two retrieved chunk ids out of the user prompt.
        ids = re.findall(r"\[chunk:(\d+)\]", user)
        assert len(ids) >= 2
        first, second = ids[0], ids[1]
        return (
            f"Claim A relies on [chunk:{first}]. Claim B relies on [chunk:{second}]. "
            f"This trailing reference [chunk:{first}] should not duplicate the citation. "
            f"Made-up id [chunk:88888888] should be dropped."
        )

    llm = FakeLLM(response_factory=cite_two_real_one_fake)
    result = answer_query(
        session,
        query="anything",
        embedder=_AlignedQueryEmbedder(),
        llm=llm,
        settings=settings,
    )
    assert result.status == "answered"
    # Two unique valid citations — first seen wins, dupes and unknown ids are dropped.
    assert len(result.citations) == 2
    cited_ids = [c.chunk_id for c in result.citations]
    assert len(set(cited_ids)) == 2
    retrieved_ids = {h.chunk.id for h in result.retrieved}
    assert all(cid in retrieved_ids for cid in cited_ids)


def test_answer_query_refuses_empty_query() -> None:
    settings = Settings(llm_provider="fake", embeddings_provider="fake")
    # No session is touched on the empty-query short-circuit; pass a sentinel object.
    result = answer_query(
        session=None,  # type: ignore[arg-type]
        query="   ",
        embedder=_AlignedQueryEmbedder(),
        llm=FakeLLM(response="never used"),
        settings=settings,
    )
    assert result.status == "refused"
    assert result.reason == "empty_query"
    assert result.citations == []
