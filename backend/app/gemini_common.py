"""Shared helpers for the Gemini (Google AI Studio) REST providers.

This module is intentionally provider-neutral: both the LLM client
(:mod:`backend.app.llm.gemini`) and the embeddings provider
(:mod:`backend.app.embeddings.gemini_provider`) import it, so the embeddings
layer never has to reach into ``llm/``.
"""

from __future__ import annotations

import httpx


def raise_for_gemini_error(response: httpx.Response, *, model: str) -> None:
    """Raise a ``RuntimeError`` with operational context on a non-2xx Gemini response.

    Gemini error bodies carry a useful ``error.message``; surface it alongside the
    status code and model so failures are debuggable. The API key and the request
    body are deliberately *not* included — error messages routinely end up in logs.
    On a 2xx response this is a no-op.
    """
    if response.is_success:
        return

    detail = ""
    try:
        body = response.json()
    except (ValueError, httpx.DecodingError):
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                detail = f": {message}"

    raise RuntimeError(
        f"Gemini request for model {model!r} failed with status {response.status_code}{detail}"
    )
