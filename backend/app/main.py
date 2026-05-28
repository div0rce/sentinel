"""FastAPI application entrypoint for Sentinel.

M0 added the liveness probe. M3 wires in the citation-grounded RAG endpoint at
``POST /query``. Routers for extract, review, and dashboard arrive in M4, M7, and M8.
"""

from fastapi import FastAPI

from backend.app.routers.query import router as query_router

app = FastAPI(title="Sentinel", version="0.1.0")

app.include_router(query_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by Docker, CI, and the load balancer health check."""
    return {"status": "ok"}
