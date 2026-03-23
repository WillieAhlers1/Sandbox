# Current State Analysis — GAP / GCP ML Framework

**Date:** 2026-03-22 (updated post-PR #25 merge)
**Branch:** `version_1`
**Scope:** Dev environment only. CI/CD is out of scope.

---

## Part 1: What We Currently Have

### 1.1 High-Level Architecture

The project is a **GCP ML Pipeline Framework** (`gcp_ml_framework`) that enables data scientists to define, build, and run ML pipelines on Google Cloud Platform without writing KFP YAML or Airflow DAGs manually.

**Core idea:** A data scientist writes a `pipeline.py` file with a fluent builder API, implements step classes with pure business logic, and the framework handles everything else — compilation to KFP YAML, Airflow DAG generation, Docker image resolution, GCS/BQ naming, and deployment to Cloud Composer + Vertex AI.

**Two-layer orchestration:**
- **Airflow (Cloud Composer)** — outer orchestrator. Handles scheduling, BQ queries, email notifications, and triggering Vertex AI pipelines.
- **Vertex AI Pipelines (KFP v2)** — inner orchestrator. Runs ML steps (training, evaluation, registration, deployment) as containerized KFP components.

### 1.2 The Unified Task Model

Two decorator types classify components:

| Decorator | TaskType | Compiled To | Runs On |
|-----------|----------|-------------|---------|
| `@task` | `TASK` | Native Airflow operator (BQInsertJobOperator, EmailOperator) | Cloud Composer |
| `@ml_task` | `ML_TASK` | `@dsl.container_component` in KFP YAML | Vertex AI Pipeline container |

The `SmartCompiler` groups consecutive `@ml_task` steps into a single KFP pipeline, wraps `@task` steps as native Airflow operators, and wires everything together in a generated Airflow DAG.

### 1.3 Component Hierarchy

```
BaseComponent (BaseSettings)
├── @task components (compiled to Airflow operators)
│   ├── BQQuery          — BigQuery SQL query
│   ├── BQTransform      — SQL transformation with destination table
│   ├── Email            — Email notification
│   └── WriteFeatures    — Feature Store metadata registration
│
└── @ml_task components (compiled to KFP container components)
    ├── TrainModel        — Train a model (data scientists subclass this)
    ├── EvaluateModel     — Evaluate with metric gates
    ├── RegisterModel     — Upload model to Vertex AI Model Registry
    └── DeployModel       — Deploy registered model to Vertex AI Endpoint
```

### 1.4 Component Lifecycle: `cli()` → `execute()` → `run()`

Every component has three layers:

1. **`cli()`** (classmethod) — Typer-based CLI entrypoint. Auto-generates `--flag` for every Pydantic field. This is what KFP calls inside the container: `python -m pipelines.training_pipeline.steps.train_house_model --project X --region Y ...`

2. **`execute()`** — Container lifecycle. Handles I/O boilerplate (temp dirs, GCS upload, output URI writing). Each component type (TrainModel, EvaluateModel, etc.) overrides this once.

3. **`run()`** — Pure business logic. Data scientists override only this. They get `self.*` autocomplete on all fields and never touch GCS/KFP/Airflow directly.

### 1.5 Pipeline Builder

Data scientists define pipelines using a fluent builder. Every component must specify `runtime_dockerfile`:

```python
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

### 1.6 Compilation Pipeline

```
pipeline.py (PipelineDefinition)
    ↓ SmartCompiler
    ├── Groups steps by task_type (consecutive @ml_task → one KFP pipeline)
    ├── Delegates ML groups to PipelineCompiler → KFP YAML
    ├── Renders @task steps as native Airflow operators
    └── Generates Airflow DAG .py file
    ↓ Output
    ├── compiled_pipelines/{name}.yaml (KFP YAML)
    └── dags/{namespace}__{name}.py (Airflow DAG)
```

**Cross-step data flow:**
- Within KFP (ml_task → ml_task): wired via KFP outputs (`dsl.OutputPath`) — e.g., TrainModel writes model URI, RegisterModel reads it.

### 1.7 Configuration System

**Layered resolution:** defaults → pipeline/config.yaml → env vars → CLI flags

- `FrameworkConfig` (BaseSettings, `env_prefix=""`) — reads `TEAM`, `PROJECT`, `ENVIRONMENT`, `BRANCH` from env vars
- `GCPConfig` (BaseSettings, `env_prefix="GCP_"`) — reads `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_COMPOSER_DAGS_PATH`, `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL`
- `MLContext` — immutable runtime context derived from config. Contains `NamingConvention` and all GCP resource names. Passed to compilers and components.

### 1.8 Naming Convention

All GCP resource names are derived from the canonical namespace: `{team}-{project}-{branch}`

| Resource | Pattern | Example |
|----------|---------|---------|
| BQ Dataset | `{team}_{project}_{branch}` (underscored) | `mlplatform_second_run_version_1` |
| GCS Bucket | `{gcp_project}-{team}-{project}` | `my-gcp-proj-mlplatform-second-run` |
| GCS Prefix | `gs://{bucket}/{branch}/` | `gs://...bucket.../version-1/` |
| Vertex Experiment | `{namespace}-{pipeline}-exp` | `mlplatform-second-run-version-1-training-pipeline-exp` |
| Vertex Model | `{namespace}-{pipeline}[-{model_name}]` | `mlplatform-second-run-version-1-house-price-regression` |
| Vertex Endpoint | `{namespace}-{pipeline}[-{model_name}]-endpoint` | `mlplatform-second-run-version-1-house-price-regression-endpoint` |
| DAG ID | `{namespace_bq}__{pipeline}` | `mlplatform_second_run_version_1__training_pipeline` |
| Docker Image | `{pipeline}--{stem}` or `{stem}` (root) | `house-price--base`, `train` |

### 1.9 Docker Image Strategy

**Post-PR #25: Per-pipeline Docker images.**

1. **`base-python`** (`docker/base/base-python/Dockerfile`) — Python 3.12 + uv + system deps. Cached, rarely rebuilt.
2. **Root defaults** (`docker/train.Dockerfile`, `docker/pipeline/Dockerfile`) — Default training images. Used when no pipeline-specific Dockerfile is set.
3. **Pipeline-specific** (`docker/pipelines/{pipeline}/base.Dockerfile`) — Per-pipeline execution image. Components specify `runtime_dockerfile="pipelines/house_price/base.Dockerfile"`.
4. **Pipeline serving** (`docker/pipelines/{pipeline}/serve.Dockerfile`) — Per-pipeline serving image (FastAPI). Components specify `serving_dockerfile="pipelines/house_price/serve.Dockerfile"`.
5. **Serving apps** (`app/{pipeline}/app.py`) — Per-pipeline FastAPI apps for Vertex AI custom container serving.

**Key fields on components:**
- `runtime_dockerfile` (on BaseComponent) — controls which Docker image the component **executes in**
- `serving_dockerfile` (on RegisterModel) — controls which Docker image is registered as the **serving container** in Vertex AI Model Registry

**Image naming:** Single source of truth in `NamingConvention.docker_image_name()`. Compiler uses `_parse_dockerfile_path()` to extract pipeline_name and stem from the path.

**Image tags:** `{branch}-{sha}` for traceability and branch isolation.

### 1.10 CLI (`gml`)

| Command | Purpose |
|---------|---------|
| `gml compile [--all]` | Generate KFP YAML + Airflow DAG from pipeline.py files |
| `gml build <pipeline>` | Build Docker images via Cloud Build |
| `gml deploy [--all]` | Compile + verify images + upload DAGs to Composer + YAML to GCS |
| `gml run <pipeline> [--local]` | Run locally (in-process) or trigger via Cloud Composer |
| `gml init project <name>` | Scaffold a new project |
| `gml init pipeline <name>` | Scaffold a new pipeline |
| `gml context show` | Display current namespace, resources, GCP project |
| `gml teardown` | Clean up deployed resources |

### 1.11 Existing Pipelines

**training_pipeline** — Single-step (post-PR #25 rollback):
1. `HouseTrainModelStep` (train) → Vertex AI

**verification_pipeline** — 3-step:
1. `BQQuery` (ingest) → Airflow
2. `BQTransform` (transform) → Airflow
3. `TrainVerifyModelStep` (train) → Vertex AI

**house_price** — 3-step (the reference pipeline with full Register+Deploy):
1. `HouseTrainModelStep` (train) → Vertex AI
2. `RegisterModel(model_name="regression")` → Vertex AI
3. `DeployModel(model_name="regression")` → Vertex AI

### 1.12 DeployModel Architecture (Post-PR #25)

DeployModel no longer uploads models. It looks up a previously registered model by `display_name` via `run_deploy()`:

1. `RegisterModel` uploads the model to Vertex AI Model Registry with a display name derived from `{namespace}-{pipeline}-{model_name}`.
2. `DeployModel` looks up that model by the same display name, raises `ValueError` if not found.
3. Endpoint display name is auto-derived: `{namespace}-{pipeline}-{model_name}-endpoint`. No `endpoint_name` field — just `model_name` which must match `RegisterModel`.
4. Each model gets its own endpoint (per-model endpoint pattern).

**Fields on DeployModel:** `model_name`, `model_display_name`, `endpoint_display_name`, `machine_type`, `min_replica_count`, `max_replica_count`, `traffic_split`, monitoring fields. No `model_uri`, no `serving_container_image`, no `endpoint_name`.

### 1.13 Business Logic (`second_run/`)

Contains `estimator.py` with model classes (e.g., `HousePredictionModel`). This is the data science team's actual model code, separate from framework code. Used by step classes via imports like `from second_run.estimator import HousePredictionModel`.

### 1.14 Serving (`app/`)

**Post-PR #25:** Per-pipeline FastAPI serving apps replace the generic `serving/handler.py`. Each pipeline that needs online serving has:
- `app/{pipeline}/app.py` — FastAPI app implementing Vertex AI custom container protocol (AIP_HTTP_PORT, AIP_HEALTH_ROUTE, AIP_PREDICT_ROUTE)
- `docker/pipelines/{pipeline}/serve.Dockerfile` — Extends the pipeline base image, adds FastAPI + uvicorn

Currently only `app/house_price/app.py` exists as the reference implementation.

### 1.15 Test Suite

**Post-PR #25 state:** 228 tests collected, 105 pass, 61 fail, 60 errors.

| Category | Test Count | Status |
|----------|-----------|--------|
| CLI | 15 | 4 pass, 11 error (conftest fixture) |
| Components | 76 | Mixed — deploy/register/train tests fail against new fields |
| Config | 20 | 2 pass, 18 fail/error (old multi-env config) |
| Pipeline | 27 | Mixed — compiler/smart_compiler errors |
| Serving | 8 | Exist but test deleted handler.py |
| Utils | 13 | 4 pass, 9 fail (old run_deploy signature) |
| Training Pipeline | 11 | Mixed — step count changed |
| Verification | 11 | Mixed — step count changed |

---

## Part 2: What the 3 Most Recent PRs Changed

### PR #25 (Most Recent): "Fixed Deployment" — `d4fb537`

**Purpose:** Restructure Docker strategy and DeployModel to use per-pipeline images and model lookup.

**Key changes:**

1. **BaseComponent field rename:** `image_name` → `runtime_dockerfile`. Every component must specify which Dockerfile it runs in.

2. **RegisterModel:** Added `serving_dockerfile` field. Three-tier serving image resolution: `serving_container_image` (full URI) → `serving_dockerfile` (path resolved by compiler) → pipeline default.

3. **DeployModel rewrite:** Removed `endpoint_name` (required), `model_uri`, `serving_container_image`. Added `model_name`. Endpoint auto-derived via `vertex_endpoint_name(pipeline_name, model_name)`.

4. **`run_deploy()` rewrite:** No longer takes `model_uri` or `serving_container_image`. Looks up registered model by display name. Raises `ValueError` if not found.

5. **`vertex_endpoint_name()` signature:** Changed from `(model_name)` to `(pipeline_name, model_name)` for uniqueness.

6. **Compiler image resolution:** `_resolve_image_uri()` now takes `dockerfile_path` string instead of `(pipeline_name, image_name)`. Added `_parse_dockerfile_path()` to extract pipeline_name and stem from path.

7. **New files:**
   - `app/house_price/app.py` — FastAPI serving app
   - `docker/pipelines/house_price/base.Dockerfile` — Pipeline-specific execution image
   - `docker/pipelines/house_price/serve.Dockerfile` — Pipeline-specific serving image

8. **`docs/updates.md`:** Added sections 14.0 (model registry naming) and 15.0 (per-model endpoints).

### PR #24: "Fixed Registry Component" — `8f06131`

See previous analysis (model versioning via `parent_model`, `sync=False`, multi-model `model_name` support).

### PR #23: "Docker Naming Convention and Image Resolution Fixes" — `d9d18ef`

See previous analysis (config simplification, Docker naming, `TaskType` extraction, BaseSettings migration).

---

## Part 3: Bugs and Gaps (Post-PR #25)

### 3.1 CRITICAL: Runtime Bugs

#### 3.1.1 `compiler.py` — `serving_image` Undefined Variable (STILL EXISTS)

```python
if isinstance(comp, (RegisterModel, DeployModel)):
    if not comp.serving_container_image:
        extra["serving_container_image"] = serving_image  # ← NameError
```

This block is both redundant (RegisterModel already handled above) AND broken (undefined variable). DeployModel no longer needs serving image resolution (it looks up registered models). **Fix: delete this entire block.**

#### 3.1.2 `train.py:77-104` — Dead Code After `raise NotImplementedError`

Experiment tracking code is unreachable. Must be moved to `execute()`.

#### 3.1.3 `conftest.py:28` — Uses `dev_project_id` Instead of `project_id`

Causes 60 test errors. GCPConfig `extra="ignore"` silently swallows the wrong field name.

#### 3.1.4 Dockerfiles Reference `third_run/` (5 files)

- `docker/pipeline/Dockerfile` — `COPY third_run/`
- `docker/train.Dockerfile` — `COPY third_run/`
- `docker/serve.Dockerfile` — `COPY third_run/` (if still exists)
- `docker/pipelines/house_price/base.Dockerfile` — `COPY third_run/`
- `pipelines/house_price/steps/train_regression_model.py` — `from third_run.estimator`

Only `second_run/` exists. Docker builds fail. Imports fail.

#### 3.1.5 `_INTERNAL_FIELDS` Contains Dead `gcp_config`

No `gcp_config` field exists on BaseComponent. Dead reference.

### 3.2 Test Suite Failures (61 fail, 60 errors)

| Category | Count | Root Cause |
|----------|-------|------------|
| conftest fixture | 60 errors | `dev_project_id` → `project_id` |
| Decorator attr name | 12 fail | Tests use `._task_type`, code uses `.task_type` |
| Config structure | 9 fail | Tests expect multi-env project mapping |
| DeployModel fields | 9 fail | Tests expect removed `endpoint_name`/`model_uri`/`serving_container_image` |
| Vertex utils | 9 fail | Tests expect old `run_deploy()` signature |
| TrainModel lifecycle | 4 fail | Tests expect `_work_dir`/`hyperparameters`/`trainer_args` |
| Pipeline definitions | 8 fail | Step counts changed (training: 6→1, verification: 6→3) |
| RegisterModel CPR | 2 fail | Tests expect CPR routes removed by PR |
| Smart compiler | 3 fail | GCPConfig fields + grouping |
| Compiler serving | 3 errors | Old `_build_derived_params` API |
| Internal fields | 1 fail | Expected set outdated |
| Serving tests | 8 exist | Test deleted `handler.py` — stale tests |

### 3.3 Functional Gaps

1. **WriteFeatures `render_operator()`** — generates invalid DAG (references undefined function)
2. **BQQuery/Email missing `__main__` blocks** — can't `--help` these components
3. **`cmd_init.py` generates wrong env var names** — scaffolded projects can't read config
4. **`get_git_branch()` KeyError risk** — `os.environ['ENVIRONMENT']` without `.get()`
5. **`context.py` duplicate `pipeline_service_account_email`** — defined twice
6. **Dead context params in compiler** — `gcs_prefix`, `staging_bucket`, etc. computed but never reach containers
7. **`smart_compiler.py` uses @dataclass** — REQS 7.0 violation
8. **Stale DAGs/YAML in `dags/` and `compiled_pipelines/`** — from old namespace configs
9. **`serving/handler.py` tests still exist** — testing deleted code
10. **No conditional/loop operators** — REQS 22.0 [P0]
11. **No mypy enforcement** — REQS 17.0
12. **No DBT integration** — REQS 19.0
13. **No AGENTS.md** — REQS 20.0
14. **Inconsistent docstrings** — REQS 10.0

### 3.4 Questions Answered by PR #25

1. **`third_run` vs `second_run`:** The directory is `second_run/`. All `third_run` references are bugs (PR #25 introduced more of them in `base.Dockerfile`).
2. **DeployModel serving container:** No longer needed — DeployModel looks up registered models. The serving image is captured during registration.
3. **CPR routes:** Intentionally removed. Per-pipeline FastAPI apps replace the generic CPR handler.
4. **Per-pipeline Docker:** Each pipeline gets its own `base.Dockerfile` (execution) and optionally `serve.Dockerfile` (serving) + `app/{pipeline}/app.py` (FastAPI).

---

## Part 4: Prioritized Action Items

See `docs/tasks/todo.md` for the full implementation plan organized by functional group.

**Summary:** 10 groups, ~35 tasks across Phase A (fix broken) and Phase B (new capabilities).

| Phase | Groups | Target |
|-------|--------|--------|
| A | 1-6: Docker, Config, Components, Compilation, Tests, Artifacts | All tests pass, compile works |
| B | 7-10: Loop/Condition, Mypy, DBT, Documentation | Full REQS coverage (except CI/CD) |

Only CI/CD (REQS 16.0) is out of scope.
