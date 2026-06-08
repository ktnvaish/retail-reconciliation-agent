# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------- #
# Stage 1 — build the virtual environment with uv (cached, reproducible)
# --------------------------------------------------------------------------- #
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Then install the project itself.
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --------------------------------------------------------------------------- #
# Stage 2 — minimal runtime image (no uv, no build tools)
# --------------------------------------------------------------------------- #
FROM python:3.11-slim-bookworm AS runtime

# Create an unprivileged user to run the app.
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

# Copy the prebuilt virtual environment and source/config.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
COPY --chown=app:app config ./config
COPY --chown=app:app data/samples ./data/samples

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data/runtime \
    DATABASE_URL=sqlite:////app/data/runtime/reconcile.db \
    NOTIFIER=mock \
    MOCK_LLM=true \
    PORT=8000

# Ensure the writable runtime directory exists and is owned by the app user.
RUN mkdir -p /app/data/runtime && chown -R app:app /app/data

USER app
EXPOSE 8000

# Honor the platform-injected $PORT (Azure Container Apps sets this).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1

CMD ["sh", "-c", "uvicorn reconcile.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
