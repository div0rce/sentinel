"""LLM provider package.

Public entry points:

* :class:`LLMClient` — the protocol all providers implement.
* :class:`FakeLLM` — deterministic, no-API client for tests.
* :class:`ClaudeClient` — hosted Anthropic Claude via the ``/v1/messages`` API.
* :func:`get_llm` — factory that maps :class:`backend.app.config.Settings` to the
  right provider.
"""

from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.app.llm.base import LLMClient, LLMResponse
from backend.app.llm.claude import ClaudeClient
from backend.app.llm.fake import FakeLLM

__all__ = [
    "ClaudeClient",
    "FakeLLM",
    "LLMClient",
    "LLMResponse",
    "get_llm",
]


def get_llm(settings: Settings | None = None) -> LLMClient:
    """Return the LLM client configured by ``settings``.

    A ``provider == "fake"`` configuration returns a :class:`FakeLLM` with empty
    canned response — tests that need behaviour set the ``response`` directly.
    """
    settings = settings or get_settings()

    provider = settings.llm_provider
    if provider == "fake":
        return FakeLLM()
    if provider == "anthropic":
        return ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}")
