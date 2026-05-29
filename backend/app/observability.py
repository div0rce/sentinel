"""Structured logging + a request-id middleware (M10).

Two responsibilities:

* :func:`configure_logging` wires ``structlog`` for JSON output suitable for
  CloudWatch / any log aggregator that ingests stdout. Production logs are
  one-line JSON with a stable schema; local development can flip to a friendlier
  console renderer via the ``SENTINEL_LOG_FORMAT=console`` env var.
* :class:`RequestIdMiddleware` assigns a stable id to every HTTP request, binds
  it to the structlog context, surfaces it on the response as
  ``X-Request-Id``, and exposes it on ``request.state.request_id`` so
  application code (notably :mod:`backend.app.audit`) can persist it.

Tests in ``backend/tests/test_request_id.py`` pin the middleware contract.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_LENGTH_LIMIT = 64


def configure_logging() -> None:
    """Configure structlog + the stdlib root logger for the application.

    Idempotent. Safe to call from app startup *and* from CLIs (``make seed``,
    ``make eval``) so every entry point produces the same shape of log.
    """
    log_level_name = os.environ.get("SENTINEL_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(log_level_name, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )

    use_console = os.environ.get("SENTINEL_LOG_FORMAT", "json").lower() == "console"
    renderer: structlog.types.Processor
    if use_console:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _generate_request_id() -> str:
    return uuid.uuid4().hex


def _sanitise_inbound(value: str) -> str | None:
    """Accept caller-supplied request ids if they are short and printable.

    Inbound headers are untrusted; we strip them to length and to a conservative
    character set so a hostile client cannot push attacker-controlled bytes
    into our log pipeline.
    """
    candidate = value.strip()
    if not candidate or len(candidate) > REQUEST_ID_LENGTH_LIMIT:
        return None
    if not all(c.isalnum() or c in "-_" for c in candidate):
        return None
    return candidate


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind a request id to every request, the structlog context, and the response."""

    HEADER_NAME = REQUEST_ID_HEADER

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound = request.headers.get(self.HEADER_NAME, "")
        request_id = _sanitise_inbound(inbound) or _generate_request_id()
        request.state.request_id = request_id

        # Bind for the duration of the request so any structlog call inside the
        # handler picks up the request_id without plumbing it through.
        token = structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            # ``token`` is a Mapping[str, contextvars.Token]; clear-by-key is the
            # supported way to undo the bind on exit.
            structlog.contextvars.unbind_contextvars(*token.keys())

        response.headers[self.HEADER_NAME] = request_id
        return response


def get_request_id(request: Request) -> str | None:
    """Convenience getter for handlers that want to forward the id (e.g., to
    :func:`backend.app.audit.emit_*`)."""
    return getattr(request.state, "request_id", None)
