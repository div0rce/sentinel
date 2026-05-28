"""Embedding provider package.

Public entry points:

* :class:`EmbeddingProvider` — the protocol all providers implement.
* :class:`FakeEmbedder` — deterministic, no-API embedder for tests/CI.
* :class:`OpenAIEmbedder` — hosted ``text-embedding-3-*`` via OpenAI's REST API.
* :func:`get_embedder` — factory that maps :class:`backend.app.config.Settings` to the
  right provider, validating that the runtime ``embedding_dim`` matches the canonical
  database schema dimension before any vector is generated.
"""

from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.app.embeddings.base import EmbeddingProvider
from backend.app.embeddings.fake import FakeEmbedder
from backend.app.embeddings.openai_provider import OpenAIEmbedder
from backend.app.models import SCHEMA_EMBEDDING_DIM

__all__ = [
    "EmbeddingProvider",
    "FakeEmbedder",
    "OpenAIEmbedder",
    "get_embedder",
]


def get_embedder(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the embedder configured by ``settings``.

    Raises :class:`ValueError` if the configured runtime dimension would produce
    vectors that do not fit the database's ``vector(SCHEMA_EMBEDDING_DIM)`` column.
    Failing here, before any embedding work happens, gives a single, loud,
    deterministic error rather than a runtime ``DataError`` deep inside an INSERT.
    """
    settings = settings or get_settings()

    if settings.embedding_dim != SCHEMA_EMBEDDING_DIM:
        raise ValueError(
            f"EMBEDDING_DIM ({settings.embedding_dim}) does not match the database "
            f"schema dimension SCHEMA_EMBEDDING_DIM ({SCHEMA_EMBEDDING_DIM}). Either "
            f"adjust the env var or write a migration to alter chunks.embedding."
        )

    provider = settings.embeddings_provider
    if provider == "fake":
        return FakeEmbedder(dim=SCHEMA_EMBEDDING_DIM)
    if provider == "openai":
        return OpenAIEmbedder(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dim=SCHEMA_EMBEDDING_DIM,
        )
    if provider == "voyage":
        # Voyage support arrives in a later milestone; fail loudly so misconfiguration
        # in CI or production is surfaced before any ingest work runs.
        raise NotImplementedError(
            "Voyage provider is not implemented yet; set EMBEDDINGS_PROVIDER to "
            "'openai' or 'fake' for now."
        )
    raise ValueError(f"Unknown embeddings provider: {provider!r}")
