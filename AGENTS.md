# AGENTS.md — AI Coding Context

## Project Overview

GCP ML Pipeline Framework (`gcp_ml_framework`) — a Python framework + CLI (`gml`) that enables data scientists to define ML pipelines in pure Python using a fluent builder API. The framework auto-compiles pipeline definitions into Airflow DAGs for Cloud Composer orchestration and KFP v2 YAML for Vertex AI pipeline execution.

## Architecture

- **Component model:** `@task` (Airflow operators) and `@ml_task` (Vertex AI containers)
- **Pipeline builder:** `Pipeline(name).add(component).build()` — single `.add()` API
- **Smart compiler:** Auto-groups consecutive `@ml_task` steps into Vertex AI pipeline, wraps all in Airflow DAG
- **Component lifecycle:** `cli()` → `execute()` → `run()`. Data scientists override `run()` only.
- **Naming:** `NamingConvention` is the single source of truth for all GCP resource names
- **Docker:** Per-pipeline images: `base.Dockerfile` (execution) + `serve.Dockerfile` (serving)

## Key Commands

```bash
uv sync                                          # Install dependencies
UV_ENV_FILE=.env uv run -- gml compile --all     # Compile pipelines
UV_ENV_FILE=.env uv run -- gml build <pipeline>  # Build Docker images
UV_ENV_FILE=.env uv run -- gml deploy --all      # Deploy to GCP
UV_ENV_FILE=.env uv run -- gml run <pipeline> --local  # Run locally
uv run -- pytest tests/ -m unit -v               # Run tests
uv run -- ruff check gcp_ml_framework tests      # Lint
uv run -- mypy gcp_ml_framework/                 # Type check
```

## Project Structure

- `gcp_ml_framework/` — Framework library
- `pipelines/` — Pipeline definitions (`pipeline.py` + `steps/`)
- `second_run/` — Shared business logic
- `app/` — Per-pipeline FastAPI serving apps
- `docker/` — `base/base-python/` + `pipelines/{name}/` (base + serve)
- `tests/` — Unit tests (pytest, `@pytest.mark.unit`)

## Configuration

`.env` with `TEAM`, `PROJECT`, `ENVIRONMENT`, `GCP_PROJECT_ID`, `GCP_REGION`.
`FrameworkConfig` uses `env_prefix=""`. `GCPConfig` uses `env_prefix="GCP_"`.

## Design Principles

1. `NamingConvention` is single source of truth for ALL resource names
2. `RegisterModel` is the SINGLE OWNER of the serving container image
3. `model_name` is the CONTRACT between `RegisterModel` and `DeployModel`
4. Generated DAGs must have ZERO `gcp_ml_framework` imports
5. `enable_caching=False` on RunPipelineJobOperator
6. Two Dockerfiles per pipeline: `base.Dockerfile` + `serve.Dockerfile`

## Testing

TDD: write tests first. Three tiers: unit (mocked), integration (real GCP dev), e2e (full Vertex AI).
All tests use `@pytest.mark.unit`. Run with `uv run -- pytest tests/ -m unit -v`.
