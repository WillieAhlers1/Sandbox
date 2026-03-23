# Quickstart

Get a working ML pipeline running on GCP from scratch.

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.12+ | `python --version` |
| uv | latest | `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| gcloud CLI | latest | `gcloud --version` |
| Docker | latest | `docker --version` (needed for local image testing only) |

GCP authentication:

```bash
gcloud auth login
gcloud auth application-default login
```

## Clone and Install

```bash
git clone <repo-url> && cd second-run
uv sync
```

This installs all dependencies including dev tools (pytest, ruff, mypy). The project uses `uv` exclusively -- never use `pip` or `poetry`.

## Configure `.env`

Copy the example and fill in real values:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# --- Identity (required) ---
TEAM=mlplatform              # Your team slug (used in all GCP resource names)
PROJECT=second_run           # Project slug (used in all GCP resource names)
ENVIRONMENT=local            # One of: local, dev, staging, prod

# --- GCP (required for non-local) ---
GCP_PROJECT_ID=prj-my-sandbox                         # Your GCP project ID
GCP_REGION=us-east4                                    # GCP region for Vertex AI

# --- Cloud Composer (required for deploy/run) ---
GCP_COMPOSER_DAGS_PATH=gs://composer-bucket/dags       # GCS path to Composer DAGs bucket
GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL=sa@project.iam.gserviceaccount.com
```

How variables map to framework config:
- `TEAM`, `PROJECT`, `ENVIRONMENT` are read by `FrameworkConfig` (no prefix)
- `GCP_PROJECT_ID`, `GCP_REGION`, etc. are read by `GCPConfig` (prefix `GCP_`)
- `BRANCH` is auto-detected from git in local mode -- you do not set it manually
- All GCP resource names derive from `{team}-{project}-{branch}` via `NamingConvention`

## Your First Pipeline: house_price

The `house_price` pipeline is the reference implementation. It demonstrates the simplest pipeline: train, register, deploy.

```
pipelines/house_price/
  pipeline.py              # Pipeline definition
  steps/
    train_regression_model.py   # Training step (subclasses TrainModel)
  sql/
    house_price_features.sql    # SQL for feature extraction
```

Here is the full pipeline definition (`pipelines/house_price/pipeline.py`):

```python
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from pipelines.house_price.steps.train_regression_model import HouseTrainModelStep

pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(HouseTrainModelStep(
        component_name="Regression Model",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .add(RegisterModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
        serving_dockerfile="pipelines/house_price/serve.Dockerfile",
    ))
    .add(DeployModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .build()
)
```

Key things to notice:
- Every component sets `runtime_dockerfile` (the image it executes in)
- `serving_dockerfile` is only on `RegisterModel` (it owns the serving image)
- `model_name="regression"` is the same on both `RegisterModel` and `DeployModel` (this is the contract)

## Compile

Compile all pipelines to KFP YAML and Airflow DAG files:

```bash
UV_ENV_FILE=.env uv run -- gml compile --all
```

Or compile a single pipeline:

```bash
UV_ENV_FILE=.env uv run -- gml compile house_price
```

Output:
- `compiled_pipelines/*.yaml` -- KFP pipeline YAML for Vertex AI
- `dags/*.py` -- Airflow DAG files for Cloud Composer

Both directories are generated artifacts. Do not edit them manually.

## Build Docker Images

Build pipeline Docker images via Google Cloud Build:

```bash
UV_ENV_FILE=.env uv run -- gml build house_price
```

This submits a Cloud Build job that builds three images in order:
1. `base-python` -- shared Python foundation
2. `house-price--base` -- pipeline execution image
3. `house-price--serve` -- pipeline serving image (extends base)

Images are tagged with `{branch}-{short_sha}` for traceability. Never use `:latest` in production.

## Deploy

Deploy compiles first (if needed), then uploads everything to GCS and Composer:

```bash
UV_ENV_FILE=.env uv run -- gml deploy --all
```

What this does:
1. Compiles all pipelines (`gml compile --all`)
2. Verifies Docker images exist in Artifact Registry
3. Uploads DAG files to the Composer GCS bucket
4. Uploads compiled pipeline YAMLs to GCS
5. Deploys feature schemas (if present)

Preview what would be deployed without actually deploying:

```bash
UV_ENV_FILE=.env uv run -- gml deploy --all --dry-run
```

## Run Locally

Execute a pipeline in-process against real GCP dev resources:

```bash
UV_ENV_FILE=.env uv run -- gml run house_price --local
```

This runs every step sequentially in your local Python process. It hits real BigQuery, GCS, and Vertex AI -- there are no mocks or local substitutes.

Override the run date:

```bash
UV_ENV_FILE=.env uv run -- gml run house_price --local --run-date 2024-06-15
```

## Run via Composer

Trigger the deployed DAG in Cloud Composer:

```bash
UV_ENV_FILE=.env uv run -- gml run house_price
```

This calls `gcloud composer environments run ... dags trigger` under the hood. The DAG must already be deployed (`gml deploy`). After deploying, wait ~5 minutes for Composer to pick up the new DAG files.

## Run Tests

Run unit tests (fast, no GCP credentials needed):

```bash
uv run -- pytest tests/ -m unit -v
```

Run integration tests (requires GCP credentials and dev project):

```bash
UV_ENV_FILE=.env uv run -- pytest tests/ -m integration -v
```

Run all lint and type checks:

```bash
uv run -- ruff check gcp_ml_framework tests
uv run -- mypy gcp_ml_framework/
```

## Summary of Commands

| What | Command |
|------|---------|
| Install | `uv sync` |
| Compile all | `UV_ENV_FILE=.env uv run -- gml compile --all` |
| Build images | `UV_ENV_FILE=.env uv run -- gml build house_price` |
| Deploy all | `UV_ENV_FILE=.env uv run -- gml deploy --all` |
| Run locally | `UV_ENV_FILE=.env uv run -- gml run house_price --local` |
| Run via Composer | `UV_ENV_FILE=.env uv run -- gml run house_price` |
| Unit tests | `uv run -- pytest tests/ -m unit -v` |
| Lint | `uv run -- ruff check gcp_ml_framework tests` |
| Type check | `uv run -- mypy gcp_ml_framework/` |
