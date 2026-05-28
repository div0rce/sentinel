"""Anthropic Claude messages API client.

Talks to the public ``/v1/messages`` endpoint with ``httpx`` directly — the messages
API is small enough that adding the official SDK as a dep is unwarranted, and going
through ``httpx`` keeps the dependency footprint identical to the OpenAI embedder.

CI never exercises this client (``LLM_PROVIDER=fake``); it exists so production
deployments can flip the provider via env without code changes.
"""

from __future__ import annotations

import httpx

from backend.app.llm.base import LLMResponse


class ClaudeClient:
    """Anthropic ``/v1/messages`` provider."""

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_API_VERSION = "2023-06-01"
    DEFAULT_TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to use ClaudeClient")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
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
        response = httpx.post(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self._api_version,
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()

        # Concatenate text blocks from the content array. Tool-use and other block
        # types are ignored for now — M3 only needs text completions.
        content = body.get("content", [])
        text_parts: list[str] = []
        for block in content:
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        text = "".join(text_parts)

        return LLMResponse(
            text=text,
            model=str(body.get("model", self._model)),
            stop_reason=body.get("stop_reason"),
        )
