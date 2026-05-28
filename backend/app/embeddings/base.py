"""Embedding provider interface.

The pipeline talks to a hosted embedding service through an :class:`EmbeddingProvider`.
Two concrete implementations live alongside this module:

* :class:`backend.app.embeddings.fake.FakeEmbedder` — deterministic, hashes text into
  vectors. Used in CI and local tests so embeddings are free, fast, and reproducible.
* :class:`backend.app.embeddings.openai_provider.OpenAIEmbedder` — POSTs to OpenAI's
  ``/v1/embeddings`` endpoint and returns the model's vectors.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Something that turns texts into fixed-dimensional float vectors.

    Implementations MUST return vectors whose length matches :attr:`dim`. Callers
    (notably the M2 ingest pipeline) validate the dimension against the database
    schema before insertion, so a mismatch is loud rather than silent.
    """

    @property
    def dim(self) -> int:
        """Output vector dimension."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed each text and return one vector per input, in the same order.

        Implementations should be batched where the underlying API supports it; the
        chunking pipeline issues hundreds of texts per document.
        """
        ...
