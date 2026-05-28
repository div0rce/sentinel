"""pgvector cosine-similarity retrieval over chunks.

The :func:`cosine_top_k` function takes a pre-computed query vector and returns the
top-k chunks ordered by cosine similarity (highest first). Embedding the query string
is the caller's job — keeping it out of this module makes the SQL pure and lets the
ingestion-time embedder be shared with the query-time embedder.

Score semantics: pgvector's ``<=>`` operator returns *cosine distance* (``1 - cos``).
We expose ``score = 1 - distance`` so larger is better and 1.0 is a perfect match,
which is what callers and the M3 citation-or-refuse policy want.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Chunk


@dataclass(frozen=True, slots=True)
class ChunkScore:
    """A retrieved chunk paired with its cosine similarity to the query."""

    chunk: Chunk
    score: float


def cosine_top_k(
    session: Session,
    *,
    query_vec: Sequence[float],
    k: int,
) -> list[ChunkScore]:
    """Return the ``k`` chunks closest to ``query_vec`` by cosine similarity.

    Chunks with NULL embeddings (e.g., legacy rows pre-M2) are skipped — they cannot
    participate in vector search. Result is sorted by descending similarity, ties
    broken by chunk id ascending so output order is deterministic.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not query_vec:
        raise ValueError("query_vec must be non-empty")

    distance = Chunk.embedding.cosine_distance(query_vec)
    stmt = (
        select(Chunk, distance.label("distance"))
        .where(Chunk.embedding.is_not(None))
        .order_by(distance.asc(), Chunk.id.asc())
        .limit(k)
    )
    rows = session.execute(stmt).all()
    return [ChunkScore(chunk=row[0], score=float(1.0 - row[1])) for row in rows]
