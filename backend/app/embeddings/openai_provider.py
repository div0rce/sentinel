"""OpenAI embedding provider.

Wraps a tiny POST against ``/v1/embeddings`` so the rest of the pipeline can swap
providers behind :class:`backend.app.embeddings.base.EmbeddingProvider`. The OpenAI
SDK is intentionally not a dependency — the embeddings endpoint is small and stable,
and bringing in the SDK doubles the wheel surface for one HTTP call.

CI never exercises this provider (no API key, ``EMBEDDINGS_PROVIDER=fake``). It exists
so production deployments can flip the provider via env without code changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx


class OpenAIEmbedder:
    """OpenAI ``/v1/embeddings`` provider."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
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
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required to use OpenAIEmbedder")
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
        if not texts:
            return []
        # OpenAI accepts a list input and returns one embedding per input in order.
        response = httpx.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": list(texts), "dimensions": self._dim},
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        # Sort by index defensively in case OpenAI ever returns out-of-order results.
        items = sorted(body["data"], key=lambda d: int(d["index"]))
        vectors: list[list[float]] = [list(item["embedding"]) for item in items]
        for vec in vectors:
            if len(vec) != self._dim:
                raise RuntimeError(
                    f"OpenAI returned vector of length {len(vec)}, expected {self._dim}"
                )
        return vectors
