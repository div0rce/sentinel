"""FastAPI application entrypoint for Sentinel.

M0 ships only the liveness probe. Routers for query, extract, review, and
dashboard are added in their respective milestones (M3, M4, M7, M8).
"""

from fastapi import FastAPI

app = FastAPI(title="Sentinel", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by Docker, CI, and the load balancer health check."""
    return {"status": "ok"}
