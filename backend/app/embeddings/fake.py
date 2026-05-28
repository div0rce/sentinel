"""Deterministic, hash-based embedder used in tests, CI, and local development.

Same input text → same output vector. Vectors are L2-normalized so cosine similarity
is well-defined and the dot product equals the cosine. Outputs match the database's
canonical ``vector(SCHEMA_EMBEDDING_DIM)`` shape so they round-trip through pgvector
without runtime dimension mismatches.

This embedder is intentionally trivial. It is **not** a meaningful semantic
representation — its job is to give the rest of the pipeline real-shaped vectors so
the storage, retrieval, and workflow layers can be tested without API calls.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence

from backend.app.models import SCHEMA_EMBEDDING_DIM


class FakeEmbedder:
    """Deterministic embedder. ``embed(text)`` is a pure function of ``text``."""

    def __init__(self, dim: int = SCHEMA_EMBEDDING_DIM) -> None:
        if dim < 1:
            raise ValueError(f"dim must be >= 1, got {dim}")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        # Stretch a SHA-256 seed into ``dim`` IEEE-754 floats by re-hashing. The
        # specific scheme is unimportant; what matters is that it is deterministic,
        # has full coverage over the hashed-byte distribution, and produces a vector
        # of exactly ``self._dim`` floats.
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        bytes_needed = self._dim * 4  # 4 bytes per float32
        chunks: list[bytes] = []
        chunk = seed
        while sum(len(c) for c in chunks) < bytes_needed:
            chunks.append(chunk)
            chunk = hashlib.sha256(chunk).digest()
        raw = b"".join(chunks)[:bytes_needed]
        floats = list(struct.unpack(f"{self._dim}f", raw))

        # Replace any NaN/Inf produced by spurious bit patterns with deterministic
        # zeros. Then L2-normalize. If the vector is all-zero (vanishingly unlikely)
        # fall back to a fixed unit vector so downstream cosine arithmetic stays
        # finite.
        floats = [0.0 if not math.isfinite(f) else f for f in floats]
        magnitude = math.sqrt(sum(f * f for f in floats))
        if magnitude == 0.0:
            unit = [0.0] * self._dim
            unit[0] = 1.0
            return unit
        return [f / magnitude for f in floats]
