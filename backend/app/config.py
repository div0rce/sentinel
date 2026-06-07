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
    embeddings_provider: Literal["openai", "voyage", "gemini", "fake"] = "openai"
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model id used when embeddings_provider='openai'.",
    )
    gemini_embedding_model: str = Field(
        default="gemini-embedding-2",
        description=(
            "Gemini embedding model id used when embeddings_provider='gemini'. Supports "
            "flexible output dimensions (128–3072); EMBEDDING_DIM must still equal the "
            "database schema dimension (1536)."
        ),
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

    llm_provider: Literal["anthropic", "gemini", "fake"] = "anthropic"
    claude_model: str = Field(
        default="claude-sonnet-4-6",
        description=(
            "Anthropic model id used when llm_provider='anthropic'. The 4.6-generation "
            "ids use a dateless format that is itself a pinned snapshot (per Anthropic's "
            "model-versioning docs); bumping this default is intentional."
        ),
    )
    gemini_model: str = Field(
        default="gemini-3.5-flash",
        description=(
            "Gemini model id used when llm_provider='gemini'. If 'gemini-3.5-flash' is "
            "not available to your account/region, 'gemini-2.5-flash' is a stable "
            "fallback."
        ),
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        description="Base URL for the Gemini (Google AI Studio) REST API.",
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
    gemini_api_key: str = ""
    google_api_key: str = Field(
        default="",
        description=(
            "Fallback for GEMINI_API_KEY. Google AI Studio keys work under either name; "
            "GEMINI_API_KEY is the documented one and takes precedence."
        ),
    )

    # --- Retrieval and review thresholds (consumed from M3/M5 onward) -------------

    retrieval_top_k: int = Field(default=5, ge=1)
    retrieval_min_score: float = Field(default=0.30, ge=0.0, le=1.0)
    confidence_review_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # --- Guardrails (consumed from M5 onward) -------------------------------------

    pii_redaction_enabled: bool = Field(
        default=True,
        description=(
            "Default-on. When True, deterministic PII regex redaction is applied "
            "before storage (in the ingest pipeline) and before any LLM call (in the "
            "RAG and extract prompt builders). Disable only for local debugging "
            "against synthetic inputs you control."
        ),
    )

    # --- Resolved-by-provider model labels (consumed by the eval harness) ---------

    @property
    def active_llm_model(self) -> str:
        """Model id of the *currently selected* LLM provider.

        Used by the eval harness so RESULTS.md reports the model that actually ran
        rather than always labelling it with ``claude_model`` (Golden Rule #5).
        """
        if self.llm_provider == "anthropic":
            return self.claude_model
        if self.llm_provider == "gemini":
            return self.gemini_model
        return "fake-llm"

    @property
    def active_embedding_model(self) -> str:
        """Embedding model id of the *currently selected* embeddings provider."""
        if self.embeddings_provider == "openai":
            return self.openai_embedding_model
        if self.embeddings_provider == "gemini":
            return self.gemini_embedding_model
        # 'voyage' has no model field yet (provider unimplemented) and 'fake' is
        # non-semantic; fall back to the provider name so the label is never wrong.
        return self.embeddings_provider


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` instance, parsing env vars on first call."""
    return Settings()
