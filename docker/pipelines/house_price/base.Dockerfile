# House price base image — framework + all pipeline deps.
# Used for training steps and as the base for serve.Dockerfile.
ARG BASE_IMAGE=base-python
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gcc && \
    rm -rf /var/lib/apt/lists/*

# --- Layer 1: Dependencies (cached unless pyproject.toml/uv.lock change) ---
COPY pyproject.toml uv.lock .python-version README.md /app/
COPY gcp_ml_framework/ /app/gcp_ml_framework/
COPY second_run/ /app/second_run/
COPY pipelines/ /app/pipelines/

RUN python -m venv /app/.venv

RUN uv sync --all-groups --all-extras --frozen
