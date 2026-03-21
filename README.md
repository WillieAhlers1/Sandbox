# GCP ML Framework

A pip-installable ML platform framework where data scientists define pipelines with simple Python decorators (`@task`, `@ml_task`), write business logic in `run()` methods, and the framework handles compilation to KFP YAML, Airflow DAG generation, Docker image management, and deployment to Vertex AI via Cloud Composer.

## Architecture

- **Unified task model** — `@task` (lightweight Airflow operators) and `@ml_task` (Vertex AI container components) decorators. Data scientists learn one system.
- **Smart compiler** — auto-groups consecutive `@ml_task` steps into a Vertex AI pipeline and wraps everything in an Airflow DAG.
- **Composer as sole orchestrator** — all pipeline execution goes through Cloud Composer. No direct Vertex AI submission from CLI.
- **2-layer Docker** — `base-python` (cached, changes rarely) → `{pipeline-name}` image (all deps + source).
- **Cloud Build for all builds** — `gml build` wraps `gcloud builds submit`. No Docker Desktop required.
- **Environment via env var** — `GML_ENVIRONMENT` set by CI/CD or `.env`. Not derived from git.
- **Branch isolation** — every branch gets its own BQ dataset, GCS paths, DAG, and Vertex AI pipeline namespace.

## How It Works

```
pipeline.py  -->  gml compile  -->  KFP YAML + Airflow DAG
                                        |
                                  gml build  -->  Cloud Build --> Artifact Registry
                                        |
                                  gml deploy -->  Composer (DAG) + GCS (YAML)
                                        |
                                  gml run    -->  Composer DAG --> Vertex AI Pipeline
```

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url> && cd <repo>
uv sync

# 2. Configure environment
cp .env.example .env
# Fill in GCP project IDs, team, project name, service accounts

# 3. Compile pipelines to KFP YAML + Airflow DAG
UV_ENV_FILE=.env uv run -- gml compile --all

# 4. Build Docker images via Cloud Build
UV_ENV_FILE=.env uv run -- gml build training_pipeline

# 5. Deploy to Composer + GCS
UV_ENV_FILE=.env uv run -- gml deploy --all

# 6. Run pipeline
UV_ENV_FILE=.env uv run -- gml run training_pipeline          # via Composer
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local  # local execution against real GCP
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `gml compile [name \| --all]` | Compile pipeline(s) to KFP YAML and Airflow DAG |
| `gml build [name \| --all]` | Build Docker images via Google Cloud Build |
| `gml deploy [name \| --all]` | Deploy DAGs, pipeline YAMLs, and feature schemas |
| `gml run [name] [--local]` | Run pipeline via Composer, or `--local` for in-process execution |
| `gml init [project \| pipeline]` | Scaffold a new project or pipeline |
| `gml context show` | Show resolved environment, config, and resource names |
| `gml teardown [--branch]` | Delete ephemeral DEV resources for a branch namespace |

## Project Structure

```
gcp_ml_framework/           # Framework library
    cli/                    #   CLI commands (compile, build, deploy, run, ...)
    components/             #   BaseComponent + ML/ingestion/transformation/operators
    pipeline/               #   Pipeline builder, KFP compiler, smart compiler, local runner
    config.py               #   FrameworkConfig + GCPConfig (pydantic-settings)
    context.py              #   MLContext (immutable runtime context)
    naming.py               #   NamingConvention (all resource names, branch-namespaced)
    decorators.py           #   @task and @ml_task decorators
pipelines/                  # Pipeline definitions (each subdir has pipeline.py)
    training_pipeline/      #   Example: housing model training pipeline
second_run/                 # Shared business logic package (estimators, features)
docker/                     # Dockerfiles
    base/base-python/       #   Base image: Python 3.12 + uv
    pipeline/               #   Pipeline image: base + all deps + source
terraform/                  # Infrastructure as code
    envs/{dev,staging,prod} #   Per-environment Terraform configs
    modules/                #   Reusable modules (storage, AR, IAM, composer)
tests/                      # Three-tier test suite
    config/                 #   Config, context, naming tests
    components/             #   Component unit tests
    pipeline/               #   Builder, compiler, smart compiler tests
    cli/                    #   CLI command tests
    training_pipeline/      #   Pipeline-specific tests + E2E
scripts/                    # Build and bootstrap scripts
docs/                       # Architecture decisions and task tracking
```

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager — exclusively, no pip)
- `gcloud` CLI (authenticated with your GCP project)

### Testing

```bash
# Unit tests (fast, no GCP needed)
uv run -- pytest tests/ -m unit -v

# Integration tests (hits real GCP dev resources)
uv run -- pytest tests/ -m integration -v

# E2E tests (full pipeline on Vertex AI)
uv run -- pytest tests/ -m e2e -v

# Code quality
uv run -- ruff check gcp_ml_framework/ tests/
```

### Test Tiers

| Tier | What | Hits GCP? | Speed |
|------|------|-----------|-------|
| Unit | Framework logic, component instantiation, compiler output | No (mocked) | <30s |
| Integration | Individual step `execute()` against real BQ/GCS | Yes (dev project) | Minutes |
| E2E | Full pipeline on Vertex AI | Yes (dev project) | 5-10 min |

## Configuration

All configuration is via environment variables in `.env` (gitignored). See `.env.example` for the full reference.

Key variables:

| Variable | Description |
|----------|-------------|
| `GML_ENVIRONMENT` | Environment: `local`, `dev`, `test`, `staging`, `prod`, `experiment` |
| `GML_TEAM` | Team name (used in resource naming) |
| `GML_PROJECT` | Project name (used in resource naming) |
| `GML_GCP__DEV_PROJECT_ID` | GCP project ID for dev environment |
| `GML_GCP__REGION` | GCP region (default: `us-central1`) |
| `GML_GCP__COMPOSER_ENVIRONMENT_NAME` | Cloud Composer environment name |

### Terraform

```bash
cd terraform/envs/dev
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply
```

Requires a `terraform.tfvars` with `project_id`, `region`, `team`, `project_name`, `pipeline_sa_name`, and `composer_sa_name`.

## Project Status

- **Phase 1** — Critical fixes + test foundation (78 tests)
- **Phase 2** — Unified task architecture: `@task`/`@ml_task`, Pipeline.add(), smart compiler (128 tests)
- **Phase 2.5** — Deprecation cleanup: old DAG system removed, config simplified (127 tests)
- **Phase 3** — Cloud Build + Docker: `gml build`, 2-layer hierarchy (132 tests)
- **Phase 4** — Training pipeline E2E on GCP: full chain verified (146 tests)
- **Phase 5** — *(next)* Complete pipeline + experiment tracking
