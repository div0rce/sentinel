# syntax=docker/dockerfile:1.7
# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install build essentials only; psycopg[binary] ships its own libpq wheel so we
# don't need libpq-dev / build-essential at runtime.
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned uv release; matches the local toolchain. Upgrade in lockstep with CI.
ADD https://astral.sh/uv/0.4.24/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Resolve dependencies into a wheel cache first; only the lockfile gates the cache.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy application source last so a code-only change does not invalidate the
# dependency layer.
COPY backend ./backend
COPY alembic.ini ./alembic.ini

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    SENTINEL_LOG_FORMAT=json

# Non-root user; matches "no root by default" container hygiene.
RUN groupadd --system --gid 1000 sentinel \
    && useradd --system --uid 1000 --gid sentinel --create-home --shell /usr/sbin/nologin sentinel

WORKDIR /app

# Bring in the resolved venv + source from the builder.
COPY --from=builder /app /app

# Drop privileges before any further setup.
USER sentinel

# Use the venv-managed python; honour $PORT for ECS service-port flexibility.
ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# Liveness probe matches the FastAPI /health endpoint shipped in M0.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; \
        urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ.get(\"PORT\",\"8000\")}/health', timeout=3); \
        sys.exit(0)" || exit 1

# Single uvicorn worker is fine for the demo; ECS scales horizontally on tasks.
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
