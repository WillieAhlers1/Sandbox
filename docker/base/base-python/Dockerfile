# Change: Upgrade base-python to Python 3.12 with uv
FROM python:3.12-slim

ENV UV_NO_CACHE=1
ENV UV_NO_ENV_FILE=1
ENV UV_PROJECT_ENVIRONMENT="/app/.venv"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv && \
    apt-get purge -y --auto-remove gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"    
