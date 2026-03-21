# Unified pipeline image: framework + deps + source code
ARG BASE_IMAGE=base-python:latest
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Layer 1: Dependencies (cached unless pyproject.toml/uv.lock change) ---
COPY pyproject.toml uv.lock .python-version README.md /app/

ENV UV_NO_CACHE=0
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN uv sync --frozen --extra trainer --extra components --no-install-project

RUN apt-get purge -y --auto-remove gcc && \
    rm -rf /var/lib/apt/lists/*

# --- Layer 2: Source code (changes often, doesn't bust dep cache) ---
COPY gcp_ml_framework/ /app/gcp_ml_framework/
COPY second_run/ /app/second_run/
COPY pipelines/ /app/pipelines/

RUN uv sync --frozen --extra trainer --extra components
