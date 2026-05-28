"""Tests for :mod:`backend.app.retrieval` against the pgvector-enabled DB."""

from __future__ import annotations

import math

import pytest
from sqlalchemy.orm import Session

from backend.app.models import SCHEMA_EMBEDDING_DIM, Chunk, Document
from backend.app.retrieval import cosine_top_k


def _crafted_vector(strength: float) -> list[float]:
    """Return a unit vector whose cosine similarity with ``[1, 0, ...]`` is ``strength``.

    ``strength`` must be in [0, 1]. The vector is ``[strength, sqrt(1-strength**2), 0, …]``,
    which has L2 norm 1 and dot product ``strength`` with ``[1, 0, …]``.
    """
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be in [0, 1]")
    v = [0.0] * SCHEMA_EMBEDDING_DIM
    v[0] = strength
    v[1] = math.sqrt(max(0.0, 1.0 - strength * strength))
    return v


def _make_doc_with_chunks(
    session: Session, *, hash_suffix: str, vectors: list[list[float]]
) -> Document:
    doc = Document(hash="r" + hash_suffix.ljust(63, "0"), source=f"test://{hash_suffix}")
    session.add(doc)
    session.flush()
    for ord_, vec in enumerate(vectors):
        session.add(
            Chunk(
                document_id=doc.id,
                ord=ord_,
                text=f"chunk {ord_} for {hash_suffix} (strength encoded in vector)",
                token_count=10,
                embedding=vec,
            )
        )
    session.flush()
    return doc


def test_cosine_top_k_orders_by_descending_similarity(session: Session) -> None:
    # Three chunks at strengths 1.0, 0.7, 0.3 against the unit query [1, 0, ...].
    _make_doc_with_chunks(
        session,
        hash_suffix="ord1",
        vectors=[_crafted_vector(1.0), _crafted_vector(0.7), _crafted_vector(0.3)],
    )
    query = [0.0] * SCHEMA_EMBEDDING_DIM
    query[0] = 1.0

    hits = cosine_top_k(session, query_vec=query, k=3)
    assert len(hits) == 3

    # Expected order: strength 1.0, then 0.7, then 0.3.
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert hits[1].score == pytest.approx(0.7, abs=1e-5)
    assert hits[2].score == pytest.approx(0.3, abs=1e-5)
    # Scores strictly descending.
    assert hits[0].score > hits[1].score > hits[2].score


def test_cosine_top_k_respects_k_limit(session: Session) -> None:
    _make_doc_with_chunks(
        session,
        hash_suffix="ord2",
        vectors=[_crafted_vector(s) for s in (0.9, 0.8, 0.7, 0.6, 0.5)],
    )
    query = [0.0] * SCHEMA_EMBEDDING_DIM
    query[0] = 1.0

    hits = cosine_top_k(session, query_vec=query, k=2)
    assert len(hits) == 2
    assert hits[0].score > hits[1].score


def test_cosine_top_k_excludes_chunks_with_null_embedding(session: Session) -> None:
    # Mix vectors with a chunk that has a NULL embedding; only the embedded chunks come back.
    doc = Document(hash="r" + "null".ljust(63, "0"), source="test://null")
    session.add(doc)
    session.flush()
    null_chunk = Chunk(document_id=doc.id, ord=0, text="no embedding", token_count=2)
    embedded_chunk = Chunk(
        document_id=doc.id,
        ord=1,
        text="has embedding",
        token_count=2,
        embedding=_crafted_vector(0.5),
    )
    session.add_all([null_chunk, embedded_chunk])
    session.flush()

    query = [0.0] * SCHEMA_EMBEDDING_DIM
    query[0] = 1.0
    # Use a large enough k that the inserted chunks would be returned if eligible. The
    # assertion is property-based so other rows in the DB do not affect correctness.
    hits = cosine_top_k(session, query_vec=query, k=50)
    returned_ids = {h.chunk.id for h in hits}
    assert null_chunk.id not in returned_ids, "chunks with NULL embedding must be excluded"
    assert embedded_chunk.id in returned_ids, "chunks with non-NULL embedding must be included"


def test_cosine_top_k_self_similarity_is_one(session: Session) -> None:
    target_vec = _crafted_vector(0.6)
    _make_doc_with_chunks(session, hash_suffix="self", vectors=[target_vec])
    hits = cosine_top_k(session, query_vec=target_vec, k=1)
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)


def test_cosine_top_k_rejects_invalid_inputs(session: Session) -> None:
    with pytest.raises(ValueError):
        cosine_top_k(session, query_vec=[1.0], k=0)
    with pytest.raises(ValueError):
        cosine_top_k(session, query_vec=[], k=5)
