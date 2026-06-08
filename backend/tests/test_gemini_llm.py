"""Tests for the Gemini LLM client and its factory wiring.

No network: ``httpx.post`` is monkeypatched with a typed fake so the request shape and
response parsing are exercised offline (matching the repo's no-live-API-in-CI rule).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.llm import FakeLLM, GeminiClient, get_llm
from backend.app.llm.gemini import GeminiClient as GeminiClientDirect


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` used by the Gemini providers."""

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
    """Patch ``gemini.httpx.post`` and return a dict that captures the call kwargs."""
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

    monkeypatch.setattr("backend.app.llm.gemini.httpx.post", fake_post)
    return captured


# --- factory ------------------------------------------------------------------


def test_factory_returns_gemini_when_provider_is_gemini() -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="test-key")
    assert isinstance(get_llm(settings), GeminiClient)


def test_factory_raises_when_gemini_key_missing() -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="", google_api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        get_llm(settings)


def test_factory_falls_back_to_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="", google_api_key="goog-key")
    client = get_llm(settings)
    assert isinstance(client, GeminiClient)

    captured = _patch_post(monkeypatch, body={"candidates": []})
    client.complete(system="s", user="u", max_tokens=8, temperature=0.0)
    assert captured["headers"]["x-goog-api-key"] == "goog-key"


def test_fake_provider_still_works_without_keys() -> None:
    settings = Settings(llm_provider="fake")
    assert isinstance(get_llm(settings), FakeLLM)


# --- request shape ------------------------------------------------------------


def test_request_uses_api_key_header_and_expected_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_post(
        monkeypatch,
        body={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )
    client = GeminiClientDirect(api_key="header-key", model="gemini-3.5-flash")
    client.complete(system="be terse", user="hello", max_tokens=64, temperature=0.0)

    assert captured["headers"]["x-goog-api-key"] == "header-key"
    payload = captured["json"]
    assert payload["systemInstruction"] == {"parts": [{"text": "be terse"}]}
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert payload["generationConfig"]["temperature"] == 0.0
    assert payload["generationConfig"]["maxOutputTokens"] == 64


def test_empty_system_omits_system_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_post(monkeypatch, body={"candidates": []})
    client = GeminiClientDirect(api_key="k", model="gemini-3.5-flash")
    client.complete(system="", user="hi", max_tokens=8, temperature=0.0)
    assert "systemInstruction" not in captured["json"]


def test_timeout_forwarded_and_url_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_post(monkeypatch, body={"candidates": []})
    client = GeminiClientDirect(
        api_key="k",
        model="gemini-3.5-flash",
        base_url="https://example.test/v1beta/",  # trailing slash on purpose
        timeout=12.5,
    )
    client.complete(system="s", user="u", max_tokens=8, temperature=0.0)
    assert captured["timeout"] == 12.5
    assert captured["url"] == "https://example.test/v1beta/models/gemini-3.5-flash:generateContent"


# --- response parsing ---------------------------------------------------------


def test_concatenates_text_parts_and_maps_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        body={
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello "}, {"text": "world"}]},
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "gemini-3.5-flash-001",
        },
    )
    client = GeminiClientDirect(api_key="k", model="gemini-3.5-flash")
    result = client.complete(system="s", user="u", max_tokens=8, temperature=0.0)
    assert result.text == "Hello world"
    assert result.stop_reason == "STOP"
    assert result.model == "gemini-3.5-flash-001"


def test_empty_candidates_returns_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, body={"candidates": []})
    client = GeminiClientDirect(api_key="k", model="gemini-3.5-flash")
    result = client.complete(system="s", user="u", max_tokens=8, temperature=0.0)
    assert result.text == ""
    assert result.model == "gemini-3.5-flash"
    assert result.stop_reason is None


# --- error handling -----------------------------------------------------------


def test_non_2xx_raises_runtime_error_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        status_code=400,
        body={"error": {"message": "model not found"}},
    )
    client = GeminiClientDirect(api_key="secret-key-123", model="gemini-3.5-flash")
    with pytest.raises(RuntimeError) as excinfo:
        client.complete(system="s", user="u", max_tokens=8, temperature=0.0)

    message = str(excinfo.value)
    assert "400" in message
    assert "model not found" in message
    assert "gemini-3.5-flash" in message
    assert "secret-key-123" not in message
