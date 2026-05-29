"""FastAPI application entrypoint for Sentinel.

M0 added the liveness probe. M3 wired in the citation-grounded RAG endpoint at
``POST /query``. M4 added schema-constrained extraction at ``POST /extract``.
M7 adds the human-in-the-loop review queue at ``GET /review`` and
``POST /review/{id}/approve|reject``. The dashboard UI arrives in M8.
"""

from fastapi import FastAPI

from backend.app.routers.extract import router as extract_router
from backend.app.routers.query import router as query_router
from backend.app.routers.review import router as review_router

app = FastAPI(title="Sentinel", version="0.1.0")

app.include_router(query_router)
app.include_router(extract_router)
app.include_router(review_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by Docker, CI, and the load balancer health check."""
    return {"status": "ok"}
