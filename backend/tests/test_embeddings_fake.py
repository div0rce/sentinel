"""Tests for the embeddings package (FakeEmbedder + factory)."""

from __future__ import annotations

import math

import pytest

from backend.app.config import Settings
from backend.app.embeddings import (
    EmbeddingProvider,
    FakeEmbedder,
    OpenAIEmbedder,
    get_embedder,
)
from backend.app.models import SCHEMA_EMBEDDING_DIM


def test_fake_embedder_satisfies_protocol() -> None:
    assert isinstance(FakeEmbedder(), EmbeddingProvider)


def test_fake_embedder_default_dim_matches_schema() -> None:
    e = FakeEmbedder()
    assert e.dim == SCHEMA_EMBEDDING_DIM
    [vec] = e.embed(["hello"])
    assert len(vec) == SCHEMA_EMBEDDING_DIM


def test_fake_embedder_is_deterministic() -> None:
    a = FakeEmbedder().embed(["alpha", "beta", "alpha"])
    b = FakeEmbedder().embed(["alpha", "beta", "alpha"])
    assert a == b
    # The two 'alpha' inputs produce identical vectors.
    assert a[0] == a[2]
    # Different inputs produce different vectors.
    assert a[0] != a[1]


def test_fake_embedder_vectors_are_l2_normalized() -> None:
    [vec] = FakeEmbedder().embed(["the quick brown fox"])
    magnitude = math.sqrt(sum(x * x for x in vec))
    assert math.isclose(magnitude, 1.0, rel_tol=1e-6)


def test_fake_embedder_empty_input_returns_empty() -> None:
    assert FakeEmbedder().embed([]) == []


def test_fake_embedder_rejects_invalid_dim() -> None:
    with pytest.raises(ValueError):
        FakeEmbedder(dim=0)


def test_factory_returns_fake_when_provider_is_fake() -> None:
    settings = Settings(embeddings_provider="fake")
    embedder = get_embedder(settings)
    assert isinstance(embedder, FakeEmbedder)
    assert embedder.dim == SCHEMA_EMBEDDING_DIM


def test_factory_returns_openai_when_provider_is_openai() -> None:
    settings = Settings(embeddings_provider="openai", openai_api_key="sk-test-not-real")
    embedder = get_embedder(settings)
    assert isinstance(embedder, OpenAIEmbedder)
    assert embedder.dim == SCHEMA_EMBEDDING_DIM


def test_factory_raises_when_dim_does_not_match_schema() -> None:
    # A configured EMBEDDING_DIM that disagrees with the database schema is an early,
    # loud failure — better than a silent INSERT-time DataError.
    settings = Settings(embeddings_provider="fake", embedding_dim=SCHEMA_EMBEDDING_DIM - 1)
    with pytest.raises(ValueError, match="does not match"):
        get_embedder(settings)


def test_factory_raises_when_openai_key_missing() -> None:
    settings = Settings(embeddings_provider="openai", openai_api_key="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        get_embedder(settings)


def test_factory_voyage_is_not_implemented() -> None:
    settings = Settings(embeddings_provider="voyage")
    with pytest.raises(NotImplementedError, match="Voyage"):
        get_embedder(settings)
