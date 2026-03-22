# Default serving image: lightweight runtime for model inference.
# Suitable for batch prediction or simple online serving.
# For CPR-based serving, override in docker/pipelines/{name}/ with a
# Google pre-built base image instead.
# Use the stem name — the build script resolves "base-python" to the full tag.
ARG BASE_IMAGE=base-python
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .python-version README.md /app/
COPY gcp_ml_framework/ /app/gcp_ml_framework/
COPY third_run/ /app/third_run/
COPY pipelines/ /app/pipelines/

RUN python -m venv /app/.venv

RUN uv sync --all-groups --frozen

# Vertex AI custom container requirements:
# - Listen on AIP_HTTP_PORT (default 8080)
# - Health endpoint at AIP_HEALTH_ROUTE (default /health)
# - Prediction endpoint at AIP_PREDICT_ROUTE (default /predict)
EXPOSE 8080
