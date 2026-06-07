"""Google AI Studio / Gemini embeddings provider.

Wraps a single POST against ``:batchEmbedContents`` so the rest of the pipeline can swap
providers behind :class:`backend.app.embeddings.base.EmbeddingProvider`. Like the OpenAI
embedder, the Google SDK is intentionally not a dependency — the embeddings endpoint is
small and stable.

The REST field that controls vector size is the snake_case ``output_dimensionality`` (the
JS SDK uses camelCase ``outputDimensionality``; the REST body does not). ``gemini-embedding-2``
supports flexible dimensions, so we request exactly the schema dimension and validate the
returned length to fail loudly on any mismatch.

CI never exercises this provider (``EMBEDDINGS_PROVIDER=fake``). It exists so local runs
and deployments can flip the provider via env without code changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from backend.app.gemini_common import raise_for_gemini_error


class GeminiEmbedder:
    """Gemini ``models/{model}:batchEmbedContents`` provider."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_TIMEOUT_SECONDS = 30.0

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dim: int,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the embedder. ``dim`` is the output vector size requested from
        the API (via ``output_dimensionality``) and validated on every response;
        ``base_url`` is normalised (trailing slash stripped). Raises ``ValueError``
        when ``api_key`` is empty or ``dim < 1`` — fail fast rather than at the first
        request."""
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to use GeminiEmbedder")
        if dim < 1:
            raise ValueError(f"dim must be >= 1, got {dim}")
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` into one ``dim``-length vector each, in input order.

        Returns ``[]`` for empty input (no request issued). Raises ``RuntimeError``
        on a non-2xx response, or if the API returns the wrong number of vectors or
        a vector whose length differs from ``dim`` — surfacing a provider/dimension
        mismatch loudly rather than letting a bad vector reach pgvector."""
        if not texts:
            return []
        # batchEmbedContents returns one embedding per request, in order. The model
        # must be the fully-qualified ``models/{id}`` form inside each request object.
        requests: list[dict[str, Any]] = [
            {
                "model": f"models/{self._model}",
                "content": {"parts": [{"text": text}]},
                "output_dimensionality": self._dim,
            }
            for text in texts
        ]
        response = httpx.post(
            f"{self._base_url}/models/{self._model}:batchEmbedContents",
            headers={
                "x-goog-api-key": self._api_key,
                "content-type": "application/json",
            },
            json={"requests": requests},
            timeout=self._timeout,
        )
        raise_for_gemini_error(response, model=self._model)
        return _parse_batch_embeddings(response.json(), expected_count=len(texts), dim=self._dim)


def _parse_batch_embeddings(
    body: dict[str, Any], *, expected_count: int, dim: int
) -> list[list[float]]:
    """Extract and validate vectors from a ``batchEmbedContents`` response body.

    Returns one ``dim``-length vector per request, in order. Raises ``RuntimeError``
    if the count or any vector length disagrees with what was requested, so a
    provider/dimension mismatch fails loudly rather than reaching pgvector."""
    items = body.get("embeddings") or []
    vectors: list[list[float]] = [list(item["values"]) for item in items]
    if len(vectors) != expected_count:
        raise RuntimeError(f"Gemini returned {len(vectors)} embeddings, expected {expected_count}")
    for vec in vectors:
        if len(vec) != dim:
            raise RuntimeError(f"Gemini returned vector of length {len(vec)}, expected {dim}")
    return vectors
