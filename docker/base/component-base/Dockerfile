# Change: Replace flat pip install with uv sync in component-base
# syntax=docker/dockerfile:1
ARG BASE_IMAGE=base-python:latest
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Layer 1: Dependencies (cached unless pyproject.toml changes) ---
COPY pyproject.toml .python-version README.md /app/

ENV UV_NO_CACHE=0

RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra components --no-install-project

# Remove build tools no longer needed at runtime
RUN apt-get purge -y --auto-remove gcc && \
    rm -rf /var/lib/apt/lists/*

# --- Layer 2: Source code (changes often, but doesn't bust dep cache) ---
COPY gcp_ml_framework /app/gcp_ml_framework/
COPY second_run /app/second_run/
COPY pipelines /app/pipelines/

# Install the project itself (deps already cached above)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra components
