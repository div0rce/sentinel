"""Tests for the Gemini embeddings provider and its factory wiring.

No network: ``httpx.post`` is monkeypatched with a typed fake so the batch request shape
and response parsing are exercised offline.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.embeddings import FakeEmbedder, GeminiEmbedder, OpenAIEmbedder, get_embedder
from backend.app.embeddings.gemini_provider import GeminiEmbedder as GeminiEmbedderDirect
from backend.app.models import SCHEMA_EMBEDDING_DIM


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def is_success(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._body


def _patch_post(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> _FakeResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(status_code=status_code, body=body or {})

    monkeypatch.setattr("backend.app.embeddings.gemini_provider.httpx.post", fake_post)
    return captured


# --- factory ------------------------------------------------------------------


def test_factory_returns_gemini_when_provider_is_gemini() -> None:
    settings = Settings(embeddings_provider="gemini", gemini_api_key="test-key")
    embedder = get_embedder(settings)
    assert isinstance(embedder, GeminiEmbedder)
    assert embedder.dim == SCHEMA_EMBEDDING_DIM


def test_factory_raises_when_gemini_key_missing() -> None:
    settings = Settings(embeddings_provider="gemini", gemini_api_key="", google_api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        get_embedder(settings)


def test_factory_falls_back_to_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(embeddings_provider="gemini", gemini_api_key="", google_api_key="goog")
    embedder = get_embedder(settings)
    assert isinstance(embedder, GeminiEmbedder)

    captured = _patch_post(
        monkeypatch,
        body={"embeddings": [{"values": [0.0] * SCHEMA_EMBEDDING_DIM}]},
    )
    embedder.embed(["hello"])
    assert captured["headers"]["x-goog-api-key"] == "goog"


def test_factory_fake_and_openai_behaviour_unchanged() -> None:
    assert isinstance(get_embedder(Settings(embeddings_provider="fake")), FakeEmbedder)
    openai = get_embedder(Settings(embeddings_provider="openai", openai_api_key="sk-x"))
    assert isinstance(openai, OpenAIEmbedder)


# --- behaviour ----------------------------------------------------------------


def test_embed_empty_returns_empty() -> None:
    embedder = GeminiEmbedderDirect(api_key="k", model="gemini-embedding-2", dim=4)
    assert embedder.embed([]) == []


def test_multiple_inputs_return_vectors_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_post(
        monkeypatch,
        body={
            "embeddings": [
                {"values": [0.1, 0.2, 0.3, 0.4]},
                {"values": [0.5, 0.6, 0.7, 0.8]},
            ]
        },
    )
    embedder = GeminiEmbedderDirect(api_key="ek", model="gemini-embedding-2", dim=4)
    vectors = embedder.embed(["first", "second"])

    assert vectors == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
    assert captured["headers"]["x-goog-api-key"] == "ek"
    requests = captured["json"]["requests"]
    assert len(requests) == 2
    assert requests[0]["content"]["parts"][0]["text"] == "first"
    assert requests[0]["model"] == "models/gemini-embedding-2"
    assert all(r["output_dimensionality"] == 4 for r in requests)


def test_timeout_forwarded_and_url_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_post(monkeypatch, body={"embeddings": [{"values": [1.0, 2.0, 3.0, 4.0]}]})
    embedder = GeminiEmbedderDirect(
        api_key="k",
        model="gemini-embedding-2",
        dim=4,
        base_url="https://example.test/v1beta/",  # trailing slash on purpose
        timeout=7.0,
    )
    embedder.embed(["x"])
    assert captured["timeout"] == 7.0
    assert (
        captured["url"]
        == "https://example.test/v1beta/models/gemini-embedding-2:batchEmbedContents"
    )


def test_wrong_vector_dimension_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, body={"embeddings": [{"values": [0.1, 0.2, 0.3]}]})
    embedder = GeminiEmbedderDirect(api_key="k", model="gemini-embedding-2", dim=4)
    with pytest.raises(RuntimeError, match="length 3, expected 4"):
        embedder.embed(["x"])


def test_wrong_count_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, body={"embeddings": [{"values": [0.1, 0.2, 0.3, 0.4]}]})
    embedder = GeminiEmbedderDirect(api_key="k", model="gemini-embedding-2", dim=4)
    with pytest.raises(RuntimeError, match="1 embeddings, expected 2"):
        embedder.embed(["x", "y"])


def test_missing_key_raises() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        GeminiEmbedderDirect(api_key="", model="gemini-embedding-2", dim=4)


def test_non_2xx_raises_runtime_error_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        status_code=429,
        body={"error": {"message": "quota exceeded"}},
    )
    embedder = GeminiEmbedderDirect(api_key="secret-key-123", model="gemini-embedding-2", dim=4)
    with pytest.raises(RuntimeError) as excinfo:
        embedder.embed(["x"])

    message = str(excinfo.value)
    assert "429" in message
    assert "quota exceeded" in message
    assert "gemini-embedding-2" in message
    assert "secret-key-123" not in message
