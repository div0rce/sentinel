"""LLM client interface.

The RAG path talks to a chat-style LLM through an :class:`LLMClient`. Two concrete
implementations live alongside this module:

* :class:`backend.app.llm.fake.FakeLLM` — returns a canned text. Used by tests so the
  RAG layer can be exercised without API calls.
* :class:`backend.app.llm.claude.ClaudeClient` — POSTs to Anthropic's
  ``/v1/messages`` endpoint and returns the assistant text.

Single-turn semantics is sufficient for M3 (system prompt + user prompt → assistant
text). The Protocol is deliberately small; richer features (streaming, tool use) can
extend it in later milestones without breaking the M3 RAG contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A non-streaming LLM completion."""

    text: str
    model: str
    stop_reason: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    """Something that turns a (system, user) pair into a single completion."""

    @property
    def model_name(self) -> str:
        """Identifier of the underlying model (e.g. 'claude-3-5-sonnet-20241022')."""
        ...

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Return a single completion. Implementations should be deterministic when
        ``temperature`` is 0.0 — the eval harness in M9 relies on this."""
        ...
