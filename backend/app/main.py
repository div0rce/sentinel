"""FastAPI application entrypoint for Sentinel.

M0 added the liveness probe. M3 wired the citation-grounded RAG endpoint at
``POST /query``. M4 added schema-constrained extraction at ``POST /extract``.
M7 added the human-in-the-loop review queue at ``GET /review`` and
``POST /review/{id}/approve|reject``. M8 added dashboard KPI feeds at
``GET /dashboard/{volume,categories,confidence,sla}``. M10 adds structured
logging + the request-id middleware so every log line carries the request id
and every response surfaces it on ``X-Request-Id``.
"""

from fastapi import FastAPI

from backend.app.observability import RequestIdMiddleware, configure_logging
from backend.app.routers.dashboard import router as dashboard_router
from backend.app.routers.extract import router as extract_router
from backend.app.routers.query import router as query_router
from backend.app.routers.review import router as review_router

configure_logging()

app = FastAPI(title="Sentinel", version="0.1.0")

# Add the request-id middleware *before* including routers so every handler runs
# with the structlog context bound.
app.add_middleware(RequestIdMiddleware)

app.include_router(query_router)
app.include_router(extract_router)
app.include_router(review_router)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by Docker, CI, and the load balancer health check."""
    return {"status": "ok"}
