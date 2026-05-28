"""Deterministic LLM stub for tests and CI.

``FakeLLM(response=...)`` ignores its inputs and returns the canned ``response`` text.
Tests construct one explicitly so the RAG path can be exercised without network calls
and with full control over what the "LLM" produces — including malformed citations
and refusal scenarios.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from backend.app.llm.base import LLMResponse


@dataclass(slots=True)
class FakeLLM:
    """Returns a canned completion. ``model_name`` is fixed for determinism.

    For tests that need to vary output across calls, pass a ``response_factory``
    instead of (or in addition to) ``response``: it is called with the system+user
    prompts and returns the response text.
    """

    response: str = ""
    response_factory: Callable[[str, str], str] | None = None
    model_name: str = field(default="fake-llm")

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        if self.response_factory is not None:
            text = self.response_factory(system, user)
        else:
            text = self.response
        return LLMResponse(text=text, model=self.model_name, stop_reason="end_turn")
