ARG BASE_IMAGE=base-python:latest
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir \
    google-cloud-bigquery>=3.17 \
    google-cloud-storage>=2.16 \
    google-cloud-aiplatform>=1.49 \
    pyarrow>=15 \
    pandas>=2 \
    db-dtypes>=1.2 \
    scikit-learn>=1.4 \
    kfp==2.15.2


ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_CACHE=1
ENV UV_NO_ENV_FILE=1
ENV UV_PROJECT_ENVIRONMENT="/app/.venv"
ENV UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    vim \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv.
RUN pip install --no-cache-dir uv

# Set the working directory to /app
WORKDIR /app

# Copy dependency files and source

COPY pyproject.toml /app/
COPY .python-version /app/
COPY README.md /app/

# Copy the application into the container.
COPY gcp_ml_framework /app/gcp_ml_framework/
COPY second_run /app/second_run/
COPY pipelines /app/pipelines/

# Create a project virtual environment, install uv into it, and run sync from it.
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --no-cache-dir --upgrade pip uv && \
    /app/.venv/bin/uv sync --all-groups