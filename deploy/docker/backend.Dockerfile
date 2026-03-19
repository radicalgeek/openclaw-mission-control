# Custom Dockerfile for Hoofer cluster deployment
# Uses pip to install uv (avoids curl to astral.sh which may have network issues)
# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (keep minimal)
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

# Install uv via pip (more reliable than curl to astral.sh)
RUN pip install --no-cache-dir uv

# --- deps layer ---
FROM base AS deps

# Copy only dependency metadata first for better build caching
# NOTE: build context is repo-root, so files live under /backend.
COPY backend/pyproject.toml backend/uv.lock ./

# Create venv and sync deps (including runtime)
RUN uv sync --frozen --no-dev

# --- runtime ---
FROM base AS runtime

# Reinstall git in runtime stage (multi-stage builds need explicit package installation)
RUN apt-get update \
  && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/* \
  && git --version

# Copy virtual environment from deps stage
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Copy app source
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app

# Copy provisioning templates.
COPY backend/templates ./templates

# Default API port
EXPOSE 8000

# Run the API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
