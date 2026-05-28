"""Centralised configuration loaded from environment variables (and a local `.env`).

All settings are typed and validated by pydantic-settings. The :func:`get_settings`
accessor is cached so the env is parsed exactly once per process; tests that need to
override values clear that cache (see ``backend/tests/conftest.py``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration. Field names map to upper-case env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore unknown env vars so a fuller .env from a later milestone does not
        # break tests/CI that only need the M1 subset.
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------------

    database_url: str = Field(
        default="postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel",
        description="SQLAlchemy URL. Must use the `postgresql+psycopg` (psycopg3) driver.",
    )

    # --- Embeddings (used from M2 onward; declared now so the schema is stable) ---

    embedding_dim: int = Field(
        default=1536,
        ge=1,
        description=(
            "Runtime embedding vector dimensionality. M2 insertion code must validate this "
            "against the canonical database schema dimension before storing vectors."
        ),
    )
    embeddings_provider: Literal["openai", "voyage", "fake"] = "openai"
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model id used when embeddings_provider='openai'.",
    )

    # --- Chunking (consumed from M2 onward) ---------------------------------------

    chunk_size_tokens: int = Field(
        default=512,
        ge=1,
        description="Target window size for the sliding-window chunker, in tokens.",
    )
    chunk_overlap_tokens: int = Field(
        default=64,
        ge=0,
        description=(
            "How many tokens of overlap to keep between successive chunks. Must be strictly "
            "less than `chunk_size_tokens` (validated at chunker construction)."
        ),
    )

    # --- LLM (consumed from M3 onward) --------------------------------------------

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    claude_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Anthropic model id used when llm_provider='anthropic'.",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Sampling temperature. Pinned to 0.0 by default for determinism in CI and "
            "in the M9 evaluation harness; production may raise it but should record "
            "the value alongside any reported metric."
        ),
    )
    llm_max_tokens: int = Field(
        default=1024,
        ge=1,
        description="Cap on completion length per LLM call.",
    )

    # --- LLM / embedding API keys (unused in M1; tests and CI leave them blank) ---

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    voyage_api_key: str = ""

    # --- Retrieval and review thresholds (consumed from M3/M5 onward) -------------

    retrieval_top_k: int = Field(default=5, ge=1)
    retrieval_min_score: float = Field(default=0.30, ge=0.0, le=1.0)
    confidence_review_threshold: float = Field(default=0.75, ge=0.0, le=1.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` instance, parsing env vars on first call."""
    return Settings()
