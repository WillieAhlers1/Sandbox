# Default training image: framework + deps + source code
# Used by all pipelines unless overridden with a pipeline-specific Dockerfile.
# Use the stem name — the build script resolves "base-python" to the full tag.
ARG BASE_IMAGE=base-python
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gcc && \
    rm -rf /var/lib/apt/lists/*

# --- Layer 1: Dependencies (cached unless pyproject.toml/uv.lock change) ---
COPY pyproject.toml uv.lock .python-version README.md /app/
COPY gcp_ml_framework/ /app/gcp_ml_framework/
COPY third_run/ /app/third_run/
COPY pipelines/ /app/pipelines/

RUN python -m venv /app/.venv

RUN uv sync --all-groups --frozen
