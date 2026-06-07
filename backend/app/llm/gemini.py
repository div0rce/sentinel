"""Google AI Studio / Gemini ``generateContent`` API client.

Talks to the public ``v1beta`` ``:generateContent`` endpoint with ``httpx`` directly
— matching :class:`backend.app.llm.claude.ClaudeClient`, which deliberately avoids the
vendor SDK for one small HTTP call. A Google AI Studio key is free and low-friction, so
this provider lets the whole RAG stack run without Anthropic/OpenAI keys.

CI never exercises this client (``LLM_PROVIDER=fake``); it exists so local runs and
deployments can flip the provider via env without code changes.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.app.gemini_common import raise_for_gemini_error
from backend.app.llm.base import LLMResponse


class GeminiClient:
    """Gemini ``models/{model}:generateContent`` provider."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to use GeminiClient")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        # Only attach a system instruction when one is supplied; an empty
        # systemInstruction can be rejected by the API.
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        response = httpx.post(
            f"{self._base_url}/models/{self._model}:generateContent",
            headers={
                "x-goog-api-key": self._api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        raise_for_gemini_error(response, model=self._model)
        body = response.json()

        candidates = body.get("candidates") or []
        model = str(body.get("modelVersion") or body.get("model") or self._model)
        if not candidates:
            return LLMResponse(text="", model=model, stop_reason=None)

        first = candidates[0]
        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts if "text" in part)
        return LLMResponse(text=text, model=model, stop_reason=first.get("finishReason"))
