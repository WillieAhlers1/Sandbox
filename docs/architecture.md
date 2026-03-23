# GCP ML Framework -- Architecture Document

> Auto-generated from source code analysis. Every claim is grounded in actual file contents.

---

## Table of Contents

1. [High-Level System Architecture](#1-high-level-system-architecture)
2. [Project Directory Structure](#2-project-directory-structure)
3. [Configuration System](#3-configuration-system)
4. [Naming Convention System](#4-naming-convention-system)
5. [Component Model](#5-component-model)
6. [Pipeline Builder](#6-pipeline-builder)
7. [Pipeline Compilation Flow](#7-pipeline-compilation-flow)
8. [Docker Image Hierarchy](#8-docker-image-hierarchy)
9. [Cross-Step Data Wiring](#9-cross-step-data-wiring)
10. [Model Lifecycle](#10-model-lifecycle)
11. [Branch Isolation](#11-branch-isolation)
12. [CLI Command Reference](#12-cli-command-reference)
13. [Process Flows](#13-process-flows)
14. [Design Decisions and Trade-offs](#14-design-decisions-and-trade-offs)

---

## 1. High-Level System Architecture

```
 DATA SCIENTIST                     GML CLI                           GCP
 +------------------+    +----------------------------+    +------------------------+
 |                  |    |                            |    |                        |
 | pipelines/       |    |  gml compile               |    |  Cloud Composer        |
 |   my_pipeline/   |--->|    SmartCompiler           |--->|    (Airflow DAGs)      |
 |     pipeline.py  |    |    PipelineCompiler        |    |                        |
 |     steps/       |    |                            |    |  Vertex AI Pipelines   |
 |     sql/         |    |  gml build                 |    |    (KFP YAML)          |
 |     config.yaml  |    |    Cloud Build / Docker    |--->|                        |
 |                  |    |                            |    |  Artifact Registry     |
 | .env             |    |  gml deploy                |    |    (Docker images)     |
 | framework.yaml   |--->|    gsutil / gcloud         |--->|                        |
 |                  |    |                            |    |  BigQuery              |
 |                  |    |  gml run                   |    |    (datasets, tables)  |
 |                  |    |    --local | --composer     |--->|                        |
 |                  |    |                            |    |  GCS                   |
 |                  |    |  gml teardown              |    |    (artifacts, YAMLs)  |
 |                  |    |    delete branch resources  |--->|                        |
 +------------------+    +----------------------------+    +------------------------+
```

**Legend:**

| Node | Purpose |
|------|---------|
| `pipeline.py` | Data scientist's pipeline definition using the fluent `Pipeline` builder API |
| `steps/` | Custom component subclasses (override `run()` for business logic) |
| `sql/` | SQL files for BQ queries/transforms, with template variables |
| `.env` | Environment variables for `FrameworkConfig` and `GCPConfig` |
| `gml compile` | Splits pipeline into Airflow DAG `.py` + KFP pipeline `.yaml` |
| `gml build` | Builds Docker images via Cloud Build, pushes to Artifact Registry |
| `gml deploy` | Uploads DAGs to Composer bucket, YAMLs to GCS, feature schemas |
| `gml run` | Triggers DAG in Composer or executes all steps in-process (`--local`) |
| `gml teardown` | Deletes all branch-scoped GCP resources (GCS prefix, BQ dataset, DAGs) |

---

## 2. Project Directory Structure

```
Sandbox/
|-- gcp_ml_framework/              # Core framework (the library)
|   |-- __init__.py                #   Re-exports: Pipeline, task, ml_task, TaskType
|   |-- config.py                  #   FrameworkConfig, GCPConfig, Environment enum, load_config()
|   |-- context.py                 #   MLContext -- immutable runtime context from config + naming
|   |-- naming.py                  #   NamingConvention -- single source of truth for all GCP names
|   |-- types.py                   #   TaskType enum (TASK, ML_TASK)
|   |-- decorators.py              #   @task and @ml_task decorators
|   |-- cli/                       #   CLI sub-commands
|   |   |-- main.py                #     Typer app, registers all sub-commands
|   |   |-- _helpers.py            #     load_context(), load_pipeline(), console utilities
|   |   |-- cmd_compile.py         #     gml compile
|   |   |-- cmd_build.py           #     gml build
|   |   |-- cmd_deploy.py          #     gml deploy
|   |   |-- cmd_run.py             #     gml run (--local | Composer trigger)
|   |   |-- cmd_init.py            #     gml init project | gml init pipeline
|   |   |-- cmd_context.py         #     gml context show
|   |   |-- cmd_teardown.py        #     gml teardown --branch <branch>
|   |-- components/                #   Component library
|   |   |-- base.py                #     BaseComponent (Pydantic BaseSettings, cli(), execute(), run(), as_kfp_component())
|   |   |-- __init__.py            #     Re-exports all built-in components
|   |   |-- operators/             #     @task components (compile to Airflow operators)
|   |   |   |-- bq_query.py        #       BQQuery -> BigQueryInsertJobOperator
|   |   |   |-- email.py           #       Email -> EmailOperator
|   |   |-- transformation/        #     @task components (compile to Airflow operators)
|   |   |   |-- bq_transform.py    #       BQTransform -> BigQueryInsertJobOperator
|   |   |-- ml/                    #     @ml_task components (compile to KFP container_component)
|   |   |   |-- train.py           #       TrainModel -- training lifecycle + GCS upload
|   |   |   |-- evaluate.py        #       EvaluateModel -- metric computation + gate checking
|   |   |   |-- register.py        #       RegisterModel -- Vertex AI Model Registry upload
|   |   |   |-- deploy.py          #       DeployModel -- Vertex AI Endpoint deployment
|   |   |-- feature_store/         #     @task components
|   |   |   |-- write_features.py  #       WriteFeatures -> PythonOperator (metadata-only)
|   |-- pipeline/                  #   Pipeline construction and compilation
|   |   |-- builder.py             #     Pipeline (fluent API), PipelineStep, PipelineDefinition
|   |   |-- smart_compiler.py      #     SmartCompiler -- groups steps, generates DAG + delegates to PipelineCompiler
|   |   |-- compiler.py            #     PipelineCompiler -- builds @dsl.pipeline, compiles to KFP YAML
|   |   |-- local_runner.py        #     LocalRunner -- in-process execution (gml run --local)
|   |   |-- runner.py              #     VertexRunner -- submit KFP YAML to Vertex AI Pipelines
|   |-- serving/                   #   Generic model serving (legacy)
|   |   |-- handler.py             #     HTTP server implementing Vertex AI prediction protocol
|   |-- utils/                     #   Shared GCP SDK wrappers
|   |   |-- bq.py                  #     BigQuery helpers (delete_bq_dataset)
|   |   |-- bq_transform.py        #     run_bq_transform() for BQTransform.execute()
|   |   |-- gcs.py                 #     upload_file(), delete_gcs_prefix()
|   |   |-- vertex.py              #     run_deploy() for DeployModel
|   |   |-- evaluate.py            #     run_evaluate() -- metric computation + gates
|   |   |-- ar.py                  #     ensure_image_tag() for deploy image verification
|   |   |-- feature_store.py       #     run_write_features() for Feature Store registration
|   |-- feature_store/             #   Feature Store client and schema
|   |   |-- schema.py              #     load_entity_schemas() from YAML
|   |   |-- client.py              #     FeatureStoreClient (Vertex AI Feature Store v2)
|   |-- secrets/                   #   Secret Manager integration
|       |-- client.py              #     SecretManagerClient
|
|-- pipelines/                     # Pipeline use cases (data scientist workspace)
|   |-- house_price/               #   Pure ML pipeline (3 @ml_task steps)
|   |   |-- pipeline.py            #     Train -> Register -> Deploy
|   |   |-- steps/
|   |       |-- train_regression_model.py
|   |-- training_pipeline/         #   Mixed pipeline (2 @task + 4 @ml_task)
|   |   |-- pipeline.py            #     BQQuery -> BQTransform -> Train -> Evaluate -> Register -> Deploy
|   |   |-- steps/
|   |   |-- sql/
|   |-- verification_pipeline/     #   Mixed pipeline with monitoring
|       |-- pipeline.py            #     Same structure as training_pipeline + monitoring config
|       |-- steps/
|
|-- docker/                        # Docker image definitions (2-tier target)
|   |-- base/
|   |   |-- base-python/
|   |       |-- Dockerfile          #   Tier 0: Python 3.12 + uv (foundation)
|   |-- pipelines/
|       |-- house_price/
|           |-- base.Dockerfile     #   Tier 1: Pipeline-specific execution
|           |-- serve.Dockerfile    #   Tier 1: Pipeline-specific serving (FastAPI)
|   |-- train.Dockerfile            #   TO BE REMOVED: root-level default
|   |-- serve.Dockerfile            #   TO BE REMOVED: root-level default
|   |-- pipeline/
|   |   |-- Dockerfile              #   TO BE REMOVED: legacy unified image
|   |-- serving/
|   |   |-- Dockerfile              #   TO BE REMOVED: legacy serving image
|   |-- pipelines/
|       |-- house_price/
|           |-- train.Dockerfile    #   TO BE REMOVED: extra per-pipeline (target is base+serve only)
|
|-- app/                           # Serving applications
|   |-- house_price/
|       |-- app.py                  #   FastAPI app for house price prediction
|
|-- second_run/                    # Estimator module (custom model class)
|   |-- estimator.py
|
|-- scripts/                       # Operational scripts
|   |-- bootstrap.sh                #   One-time GCP project setup (enable APIs, create AR repo)
|   |-- docker_build.sh             #   Build pipeline Docker images (train, serve, per-pipeline)
|   |-- docker_build_base.sh        #   Build base-python foundation image
|   |-- resolve_image.py            #   Python/bash bridge for image name resolution
|   |-- seed_bq.sh                  #   Load seed CSVs into BigQuery
|
|-- terraform/                     # Infrastructure as Code
|   |-- envs/
|   |   |-- dev/main.tf             #   Dev environment (storage, AR, IAM bindings)
|   |   |-- staging/main.tf
|   |   |-- prod/main.tf
|   |-- modules/
|       |-- storage/                #   GCS bucket module
|       |-- artifact_registry/      #   AR repository module
|       |-- composer/               #   Cloud Composer module
|       |-- iam/                    #   Service account + IAM module
|
|-- dags/                          # Generated Airflow DAG files (output of gml compile)
|-- compiled_pipelines/            # Generated KFP YAML files (output of gml compile)
|-- feature_schemas/               # Feature Store entity definitions (YAML)
|-- tests/                         # Test suite
|   |-- conftest.py
|   |-- components/                 #   Component unit tests
|   |-- config/                     #   Config, context, naming tests
|   |-- pipeline/                   #   Compiler and builder tests
|   |-- cli/                        #   CLI command tests
|   |-- serving/                    #   Serving handler tests
|   |-- training_pipeline/          #   Pipeline integration tests
|   |-- verification_pipeline/
|   |-- utils/
|
|-- pyproject.toml                 # Project metadata, dependencies, CLI entrypoint
|-- cloudbuild.yaml                # Cloud Build config for image builds
|-- .env                           # Local environment variables (gitignored)
```

---

## 3. Configuration System

**Source:** `gcp_ml_framework/config.py`, `gcp_ml_framework/context.py`

### Resolution Chain

```
+------------------+     +------------------+     +------------------+     +------------------+
| 1. Defaults      |---->| 2. config.yaml   |---->| 3. Env Vars      |---->| 4. CLI Flags     |
| (Pydantic field  |     | (pipeline-level  |     | (FrameworkConfig: |     | (explicit kwargs |
|  defaults)       |     |  YAML overrides) |     |  no prefix;      |     |  via load_config |
|                  |     |                  |     |  GCPConfig:       |     |  **overrides)    |
|                  |     |                  |     |  GCP_ prefix)     |     |                  |
+------------------+     +------------------+     +------------------+     +------------------+
                                   LATER WINS -->
```

**How it works:** `load_config()` in `config.py`:
1. Starts with empty base dict
2. Merges pipeline-level `config.yaml` if provided
3. Applies explicit keyword overrides
4. Constructs `FrameworkConfig(**base)` -- Pydantic-settings auto-reads env vars

### FrameworkConfig

Defined in `gcp_ml_framework/config.py`. Uses `env_prefix=""` (bare env var names).

| Field | Type | Env Var | Description |
|-------|------|---------|-------------|
| `team` | `str` | `TEAM` | Team slug (e.g., `dsci`) |
| `project` | `str` | `PROJECT` | Project name (e.g., `gcpdemo`) |
| `branch` | `str` | `BRANCH` | Git branch (auto-detected via `get_git_branch()`) |
| `environment` | `str` | `ENVIRONMENT` | Deployment environment |
| `gcp` | `GCPConfig` | -- | Nested GCP configuration |
| `feature_store` | `FeatureStoreConfig` | -- | Feature Store settings |
| `secrets` | `SecretsConfig` | -- | Secret Manager settings |

### GCPConfig

Uses `env_prefix="GCP_"`.

| Field | Type | Env Var | Description |
|-------|------|---------|-------------|
| `project_id` | `str` | `GCP_PROJECT_ID` | GCP project ID |
| `region` | `str` | `GCP_REGION` | GCP region |
| `composer_dags_path` | `str` | `GCP_COMPOSER_DAGS_PATH` | GCS path to Composer DAGs bucket |
| `pipeline_service_account_email` | `str` | `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL` | Override pipeline SA email |

### Environment Enum

Defined in `gcp_ml_framework/config.py`:

| Value | Usage |
|-------|-------|
| `LOCAL` | Local development, no GCP interaction |
| `DEV` | Feature branches -- DAG schedule set to `None` |
| `TEST` | Test environment |
| `STAGING` | Main branch -- full schedule |
| `PROD` | Production -- tagged releases |
| `EXPERIMENT` | Experimental workloads |

### MLContext

Defined in `gcp_ml_framework/context.py`. Created via `MLContext.from_config(cfg)`.

`MLContext` is an **immutable Pydantic model** (`frozen=True`) that wraps `NamingConvention` and provides convenience pass-throughs. No component should import `FrameworkConfig` directly -- it receives `MLContext`.

Key properties: `namespace`, `bq_dataset`, `gcs_prefix`, `feature_store_id`, `pipeline_service_account`.

The `pipeline_service_account` property resolves via: explicit override > derived pattern `{team}-{project}-{env}-pipeline@{project}.iam.gserviceaccount.com`.

---

## 4. Naming Convention System

**Source:** `gcp_ml_framework/naming.py`

`NamingConvention` is the **single source of truth** for every GCP resource name. No resource name is constructed outside this module.

### Slugification Rules

Two regexes normalize inputs during `__init__`:

| Function | Regex | Replacement | Max Length | Used For |
|----------|-------|-------------|------------|----------|
| `_slugify()` | `[^a-z0-9]+` | hyphens (`-`) | 30 | GCS, AR, Vertex AI names |
| `_bq_safe()` | `[^a-z0-9_]+` | underscores (`_`) | 30 | BigQuery identifiers |

Constructor auto-slugifies: `team` (max 12), `project` (max 20), `branch` (max 30).

### Derived Resource Names

| Resource | Pattern | Method | Example (`team=dsci`, `project=gcpdemo`, `branch=feature/xyz`) |
|----------|---------|--------|-------|
| Namespace | `{team}-{project}-{branch}` | `namespace` | `dsci-gcpdemo-feature-xyz` |
| BQ namespace | `{team}_{project}_{branch}` | `namespace_bq` | `dsci_gcpdemo_feature_xyz` |
| GCS bucket (with project) | `{gcp_project}-{team}-{project}` | `gcs_bucket` | `my-gcp-proj-dsci-gcpdemo` |
| GCS bucket (without project) | `{team}-{project}` | `gcs_bucket` | `dsci-gcpdemo` |
| GCS prefix | `gs://{bucket}/{branch}/` | `gcs_prefix` | `gs://my-gcp-proj-dsci-gcpdemo/feature-xyz/` |
| GCS pipeline root | `gs://{bucket}/{branch}/pipelines/{name}` | `gcs_pipeline_root()` | `gs://.../feature-xyz/pipelines/training` |
| GCS data path | `gs://{bucket}/{branch}/data/{stage}/{dataset}` | `gcs_data_path()` | `gs://.../feature-xyz/data/raw/events` |
| GCS model path | `gs://{bucket}/{branch}/models/{name}/{version}` | `gcs_model_path()` | `gs://.../feature-xyz/models/churn/latest` |
| BQ dataset | `{team}_{project}_{branch}` | `bq_dataset` | `dsci_gcpdemo_feature_xyz` |
| BQ table | `{dataset}.{table}` | `bq_table()` | `dsci_gcpdemo_feature_xyz.training_raw` |
| BQ feature table | `{dataset}.feat_{entity}_{group}` | `bq_feature_table()` | `...feat_user_behavioral` |
| Vertex display name | `{namespace}-{pipeline}` | `vertex_pipeline_display_name()` | `dsci-gcpdemo-feature-xyz-churn` |
| Vertex experiment | `{namespace}-{pipeline}-exp` | `vertex_experiment()` | `dsci-gcpdemo-feature-xyz-churn-exp` |
| Vertex model name | `{namespace}-{pipeline}[-{model}]` | `vertex_model_name()` | `dsci-gcpdemo-feature-xyz-house-price-regression` |
| Vertex endpoint | `{namespace}-{pipeline}[-{model}]-endpoint` | `vertex_endpoint_name()` | `...-regression-endpoint` |
| Vertex training job | `{namespace}-{job}` | `vertex_training_job_name()` | `dsci-gcpdemo-feature-xyz-train` |
| AR repo | `{host}/{gcp_project}/{team}-{project}` | `artifact_registry_repo()` | `us-east4-docker.pkg.dev/my-proj/dsci-gcpdemo` |
| Image tag | `{branch}-{sha}` | `image_tag()` | `feature-xyz-a1b2c3d` |
| DAG ID | `{namespace_bq}__{pipeline}` | `dag_id()` | `dsci_gcpdemo_feature_xyz__training_pipeline` |
| Feature Store ID | `{team}_{project}` | `feature_store_id` | `dsci_gcpdemo` |
| Feature view ID | `{entity}_{group}_{branch}` | `feature_view_id()` | `user_behavioral_feature_xyz` |
| Secret name | `{namespace}-{key}` | `secret_name()` | `dsci-gcpdemo-feature-xyz-api-key` |

### Docker Image Naming

`docker_image_name()` is a `@staticmethod` -- the single source of truth shared by both Python (`PipelineCompiler`) and bash (`docker_build.sh` via `resolve_image.py`).

| Scope | Input | Output | Example |
|-------|-------|--------|---------|
| Root-level | `pipeline_name=None, stem="train"` | `{stem}` | `train` |
| Pipeline-scoped | `pipeline_name="house_price", stem="base"` | `{pipeline}--{stem}` | `house-price--base` |

The `--` double-hyphen delimiter distinguishes pipeline-scoped images from root-level ones.

Full image URI via `docker_image_uri()`: `{ar_repo}/{name}:{branch}-{sha}`

---

## 5. Component Model

**Source:** `gcp_ml_framework/components/base.py`, `gcp_ml_framework/decorators.py`

### Class Hierarchy

```
pydantic_settings.BaseSettings
  |
  +-- BaseComponent                          # Abstract base (base.py)
       |                                     #   Fields: machine_type, project, region, branch,
       |                                     #           environment, output_uri_path, run_date, dataset
       |                                     #   Methods: cli(), execute(), run(), as_kfp_component()
       |
       +-- @task components                  # Compiled to native Airflow operators
       |   |-- BQQuery                       #   -> BigQueryInsertJobOperator
       |   |-- BQTransform                   #   -> BigQueryInsertJobOperator
       |   |-- Email                         #   -> EmailOperator
       |   |-- WriteFeatures                 #   -> PythonOperator
       |
       +-- @ml_task components               # Compiled to KFP container_component
           |-- TrainModel                    #   Custom execute(): run() -> GCS upload -> write output URI
           |-- EvaluateModel                 #   Custom execute(): run() -> experiment tracking
           |-- RegisterModel                 #   SINGLE OWNER of serving container image
           |-- DeployModel                   #   Pure deployment -- NO serving image fields
```

### Design Contracts (PRs #23-#26)

1. **RegisterModel is the SINGLE OWNER of the serving container image.** It captures the serving image URI during model registration via `serving_dockerfile` or `serving_container_image`. The image is stored in the Vertex AI Model Registry alongside the model artifact.

2. **`model_name` is the CONTRACT between RegisterModel and DeployModel.** Both components use the same `model_name` value, which the compiler resolves to matching `model_display_name` and `endpoint_display_name` via `NamingConvention`.

3. **DeployModel has NO serving image fields.** It is pure deployment: find the registered model by display name, find or create an endpoint, deploy. The serving image is already captured in the Model Registry by RegisterModel.

### Component Lifecycle

```
  COMPILE TIME                    CONTAINER RUNTIME                 LOCAL RUNTIME
  (gml compile)                   (KFP container)                   (gml run --local)
  +------------------+            +------------------+              +------------------+
  | as_kfp_component |            | cli()            |              | execute()        |
  |   Pydantic fields |            |   Typer auto-gen |              |   called directly|
  |   -> KFP params   |            |   --flag per     |              |   with merged    |
  |   -> ContainerSpec |            |   field          |              |   params         |
  |   -> YAML          |            |   -> instantiate |              +--------+---------+
  +------------------+            |   -> execute()   |                       |
                                  +--------+---------+                       v
                                           |                          +------+------+
                                           v                          |   run()     |
                                  +--------+---------+                | (business   |
                                  |   execute()      |                |  logic)     |
                                  |   (I/O lifecycle) |                +-------------+
                                  |   - temp dirs     |
                                  |   - GCS upload    |
                                  |   - output URI    |
                                  +--------+---------+
                                           |
                                           v
                                  +--------+---------+
                                  |   run()          |
                                  | (data scientist  |
                                  |  overrides this) |
                                  +------------------+
```

**Key design:** Data scientists only override `run()`. The framework handles `cli()` (auto-generates `--flag` per Pydantic field), `execute()` (I/O lifecycle), and `as_kfp_component()` (KFP wiring).

### Internal Fields

Defined in `_INTERNAL_FIELDS` (`base.py`): `component_name`, `component_version`, `timeout_seconds`, `retry_count`, `cache_enabled`, `runtime_dockerfile`, `serving_dockerfile`, `model_name`. These are never exposed as CLI flags or KFP parameters.

**Note:** The current code also contains a dead `"gcp_config"` entry in `_INTERNAL_FIELDS` that should be removed (Bug 10 in current_state_analysis.md).

### Built-in Components

| Component | Decorator | Airflow Operator | Source | Key Fields |
|-----------|-----------|-----------------|--------|------------|
| `BQQuery` | `@task` | `BigQueryInsertJobOperator` | `components/operators/bq_query.py` | `sql`, `sql_file`, `destination_table`, `write_disposition` |
| `BQTransform` | `@task` | `BigQueryInsertJobOperator` | `components/transformation/bq_transform.py` | `output_table`, `sql_file`, `sql`, `write_disposition` |
| `Email` | `@task` | `EmailOperator` | `components/operators/email.py` | `to`, `subject`, `body`, `cc` |
| `WriteFeatures` | `@task` | `PythonOperator` | `components/feature_store/write_features.py` | `entity`, `feature_group`, `entity_id_column`, `feature_time_column` |
| `TrainModel` | `@ml_task` | KFP `container_component` | `components/ml/train.py` | `model_output_uri`, `job_name`, `experiment_name` |
| `EvaluateModel` | `@ml_task` | KFP `container_component` | `components/ml/evaluate.py` | `dataset_uri`, `model_uri`, `metrics`, `gate` |
| `RegisterModel` | `@ml_task` | KFP `container_component` | `components/ml/register.py` | `model_uri`, `model_display_name`, `serving_dockerfile`, `serving_container_image` |
| `DeployModel` | `@ml_task` | KFP `container_component` | `components/ml/deploy.py` | `model_display_name`, `endpoint_display_name`, `traffic_split`, `enable_monitoring` |

### @task vs @ml_task Decorators

Defined in `gcp_ml_framework/decorators.py`:

- **`@task`**: Sets `cls.task_type = TaskType.TASK`. Component compiles to a native Airflow operator. Must implement `render_operator()` returning `(code_template, imports)`.
- **`@ml_task`**: Sets `cls.task_type = TaskType.ML_TASK`. Component compiles to a KFP `container_component` via `as_kfp_component()`. Optionally accepts `machine_type`, `accelerator_type`, `accelerator_count` overrides.

---

## 6. Pipeline Builder

**Source:** `gcp_ml_framework/pipeline/builder.py`

### Fluent API

```python
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components import BQQuery, TrainModel, Email

pipeline = (
    Pipeline(name="my-pipeline", schedule="@daily")
    .add(BQQuery(sql="SELECT ..."), name="Ingest")
    .add(TrainModel(machine_type="n2-standard-8"), name="Train")
    .add(Email(to=["team@co.com"]), name="Notify")
    .build()
)
```

### Data Model

```
Pipeline (builder)
  |
  .build()
  |
  v
PipelineDefinition (frozen)
  |-- name: str
  |-- schedule: str | None
  |-- description: str
  |-- tags: list[str]
  |-- steps: list[PipelineStep]
        |-- name: str
        |-- component: BaseComponent
        |-- task_type: TaskType
```

`Pipeline.add()` reads the component's `task_type` ClassVar (set by `@task` or `@ml_task`). Default step name: `{ClassName}_{index}`.

`PipelineDefinition.has_mixed_types` returns `True` if the pipeline contains both `@task` and `@ml_task` steps.

### Three Pipeline Patterns

| Pattern | Components | Compilation Output | Example |
|---------|-----------|-------------------|---------|
| **Pure ML** | All `@ml_task` | KFP YAML + thin DAG wrapper (RunPipelineJobOperator) | `house_price` pipeline |
| **Pure ETL** | All `@task` | DAG only, no YAML | Hypothetical SQL-only pipeline |
| **Hybrid** | Mixed `@task` + `@ml_task` | DAG with native operators + RunPipelineJobOperator(s) | `training_pipeline`, `verification_pipeline` |

---

## 7. Pipeline Compilation Flow

**Source:** `gcp_ml_framework/pipeline/smart_compiler.py`, `gcp_ml_framework/pipeline/compiler.py`

This is the core of the framework -- transforming a `PipelineDefinition` into deployable artifacts.

### End-to-End Flow

```
 pipeline.py                    SmartCompiler                     Output
 +------------------+           +---------------------------+     +---------------------------+
 |                  |           |                           |     |                           |
 | Pipeline(...)    |           |  1. _group_steps()        |     |  dags/                    |
 |   .add(BQQuery)  |---------->|     Group consecutive     |---->|    {dag_id}.py            |
 |   .add(BQTrans)  |           |     same-type steps       |     |    (self-contained DAG)   |
 |   .add(Train)    |           |                           |     |                           |
 |   .add(Eval)     |           |  2. For each ML_TASK      |     |  compiled_pipelines/      |
 |   .add(Register) |           |     group: delegate to    |---->|    {pipeline_name}.yaml   |
 |   .add(Deploy)   |           |     PipelineCompiler      |     |    (KFP v2 YAML)         |
 |   .build()       |           |                           |     |                           |
 +------------------+           |  3. _generate_dag()       |     +---------------------------+
                                |     Render DAG source     |
                                |     with all groups       |
                                +---------------------------+
```

### Step 1: Step Grouping (`_group_steps`)

The `SmartCompiler` uses `itertools.groupby` to split steps into consecutive runs of the same `task_type`:

```
Input steps:    [BQQuery, BQTransform, TrainModel, EvaluateModel, RegisterModel, DeployModel]
Task types:     [TASK,    TASK,        ML_TASK,    ML_TASK,       ML_TASK,       ML_TASK     ]
                 \___________/          \________________________________________________/
Groups:          _StepGroup(0,TASK)      _StepGroup(1,ML_TASK)

Output:
  Group 0: task_type=TASK,    steps=[BQQuery, BQTransform]
  Group 1: task_type=ML_TASK, steps=[TrainModel, EvaluateModel, RegisterModel, DeployModel]
```

### Step 2: ML Group Compilation (`_compile_ml_group`)

Each `ML_TASK` group is compiled to KFP YAML by delegating to `PipelineCompiler`:

```
PipelineCompiler.compile()
  |
  _build_kfp_pipeline()
  |   |-- Build context params (project, region, dataset, experiment_name, etc.)
  |   |-- Build per-step derived params (job_name, model_display_name, etc.)
  |   |-- Create @dsl.pipeline function:
  |   |     |-- Pipeline params: run_date, dataset_uri, model_uri
  |   |     |-- For each step:
  |   |     |     1. Resolve image via _resolve_image_uri(runtime_dockerfile)
  |   |     |     2. component.as_kfp_component(step_module, base_image)
  |   |     |     3. Merge: component_fields + ctx_params + derived_params
  |   |     |     4. Wire cross-step: last_dataset_output, last_model_output
  |   |     |     5. task.after(prev_task) for sequential ordering
  |   |     |     6. Track outputs by component type
  |   |
  |   kfp.compiler.Compiler().compile(pipeline_fn, output_path)
  |
  v
  compiled_pipelines/{name}.yaml
```

### Step 3: DAG Generation (`_generate_dag`)

The `_render_dag` method generates a **self-contained Python file** with zero framework imports:

```
For TASK groups:
  Each step's component.render_operator(context, pipeline_dir) is called.
  Returns (code_template, imports) -> rendered as native Airflow operator.

For ML_TASK groups:
  Rendered as RunPipelineJobOperator pointing to the compiled YAML in GCS:
    - template_path: gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml
    - pipeline_root: gs://{bucket}/{branch}/pipeline_runs/{name}/
    - enable_caching: False
    - deferrable: True
    - service_account: pipeline SA
    - parameter_values: {"run_date": "{{ ds }}", ...bridged params}

Dependencies: sequential >> chaining across all groups.
```

### Template Fields Extension

Generated DAGs include this block when `RunPipelineJobOperator` is used:

```python
RunPipelineJobOperator.template_fields = tuple(
    dict.fromkeys(
        (*RunPipelineJobOperator.template_fields, "display_name", "parameter_values")
    )
)
```

This ensures Airflow Jinja macros (`{{ ds }}`, `{{ ds_nodash }}`) are resolved in `display_name` and `parameter_values`.

### Image Resolution (`_resolve_image_uri`)

The `PipelineCompiler` resolves `runtime_dockerfile` paths to full AR image URIs:

```
runtime_dockerfile path                  ->  (pipeline_name, stem)     ->  image name
"pipelines/house_price/base.Dockerfile"  ->  ("house_price", "base")   ->  "house-price--base"
"train.Dockerfile"                       ->  (None, "train")           ->  "train"
None (default)                           ->  (None, "train")           ->  "train"
```

Full URI: `{region}-docker.pkg.dev/{gcp_project}/{team}-{project}/{name}:{branch}-{sha}`

### Derived Parameters (`_build_derived_params`)

The compiler injects parameters that can only be resolved at compile time:

| Component Type | Derived Parameter | Source |
|---------------|-------------------|--------|
| `TrainModel` | `job_name` | `naming.vertex_training_job_name(pipeline)` |
| `TrainModel` | `model_output_uri` | `naming.gcs_model_path(pipeline)` |
| `RegisterModel` | `model_display_name` | `naming.vertex_model_name(pipeline, model_name)` |
| `RegisterModel` | `serving_container_image` | Three-tier resolution (see Section 10) |
| `DeployModel` | `model_display_name` | `naming.vertex_model_name(pipeline, model_name)` |
| `DeployModel` | `endpoint_display_name` | `naming.vertex_endpoint_name(pipeline, model_name)` |
| `WriteFeatures` | `feature_view_id` | `naming.feature_view_id(entity, group)` |

---

## 8. Docker Image Hierarchy

**Source:** `docker/` directory, `scripts/docker_build.sh`, `scripts/docker_build_base.sh`, `scripts/resolve_image.py`

### Target Architecture (Per Client PR #26 Design)

The client's design (documented in `docs/deploy.md` PR #26) is a **2-tier** hierarchy:
`base-python` (foundation) + two Dockerfiles per pipeline (`base.Dockerfile` + `serve.Dockerfile`).
Root-level default Dockerfiles are removed.

```
Tier 0: Foundation (built once, rarely changes)
+-------------------------------+
| base-python:latest            |
| docker/base/base-python/      |
|                               |
| Python 3.12-slim + uv         |
| build-essential, curl         |
| WORKDIR /app                  |
| PATH=/app/.venv/bin:$PATH     |
+---------------+---------------+
                |
                | ARG BASE_IMAGE=base-python
                |
Tier 1: Per-Pipeline Images (two per pipeline)
+-------------------------------+    +-------------------------------+
| house-price--base:{tag}       |    | house-price--serve:{tag}      |
| docker/pipelines/house_price/ |    | docker/pipelines/house_price/ |
|   base.Dockerfile             |    |   serve.Dockerfile            |
|                               |    |                               |
| Extends base-python           |    | Extends base                  |
| + framework code              |    | + FastAPI + uvicorn           |
| + all deps (uv sync)          |    | + app/house_price/            |
| + pipelines/ + second_run/    |    | EXPOSE 8080                   |
|                               |    | CMD uvicorn                   |
| Used by: TrainModel,          |    | Used by: RegisterModel        |
| EvaluateModel, RegisterModel, |    |   (serving_dockerfile)        |
| DeployModel                   |    |                               |
| (runtime_dockerfile)          |    |                               |
+-------------------------------+    +-------------------------------+
```

### Image Count Patterns

Different pipelines require different numbers of Docker images:

```
Simplest pipeline (2 images):
  base-python --> base.Dockerfile --> serve.Dockerfile
  One execution image + one serving image.

Typical pipeline (3 images):
  base-python --> base.Dockerfile --> train.Dockerfile
                                  --> serve.Dockerfile
  Separate training and serving images when deps diverge.

Multi-model pipeline (1 + 2N images):
  base-python --> base.Dockerfile --> model_A/train.Dockerfile
                                  --> model_A/serve.Dockerfile
                                  --> model_B/train.Dockerfile
                                  --> model_B/serve.Dockerfile
  One base + a train/serve pair per model.
```

The current client target for `house_price` is the simplest pattern: `base.Dockerfile` + `serve.Dockerfile`.

### Current State vs Target

**TO BE REMOVED** (per client PR #26 `docs/deploy.md`):

| File | Reason |
|------|--------|
| `docker/train.Dockerfile` | Root-level default, client says removed |
| `docker/serve.Dockerfile` | Root-level default, client says removed |
| `docker/pipeline/Dockerfile` | Legacy unified image, superseded by per-pipeline |
| `docker/serving/Dockerfile` | Legacy serving image, superseded by per-pipeline |
| `docker/pipelines/house_price/train.Dockerfile` | Extra -- client target is only `base.Dockerfile` + `serve.Dockerfile` per pipeline |

**KEEP** (correct per target):

| File | Purpose |
|------|---------|
| `docker/base/base-python/Dockerfile` | Foundation layer (Tier 0) |
| `docker/pipelines/house_price/base.Dockerfile` | Per-pipeline execution image |
| `docker/pipelines/house_price/serve.Dockerfile` | Per-pipeline serving image |

### BASE_IMAGE Resolution Logic

The build script (`docker_build.sh`) maintains an in-memory **registry** (stem -> full tag).

```
1. Seed registry: "base-python" -> "{ar_repo}/base-python:latest"

2. Build pipeline images (docker/pipelines/{name}/*.Dockerfile):
   - Read ARG BASE_IMAGE=<stem> from Dockerfile
   - Look up <stem> in registry -> resolved full tag
   - Build with --build-arg BASE_IMAGE={resolved}
   - Image name from NamingConvention.docker_image_name(pipeline, stem)
   - Register: "house-price--base" -> "{ar_repo}/house-price--base:{tag}"

NOTE: With root-level defaults removed, build script goes directly from
base-python to per-pipeline images. Build script needs updating to match.
```

### Image Tagging

All images use the tag format: `{branch_slug}-{short_sha}` (from `NamingConvention.image_tag()`).
Base-python uses `:latest` only (built separately, changes infrequently).

### Python/Bash Bridge

`scripts/resolve_image.py` calls `NamingConvention.docker_image_name()` to ensure bash and Python produce identical image names:

```bash
# In docker_build.sh:
image_name=$(python -c "
from gcp_ml_framework.naming import NamingConvention
print(NamingConvention.docker_image_name(\"$pipeline_name\", \"$stem\"))
")
```

---

## 9. Cross-Step Data Wiring

**Source:** `gcp_ml_framework/pipeline/compiler.py`, `gcp_ml_framework/pipeline/smart_compiler.py`, `gcp_ml_framework/pipeline/local_runner.py`

### Output Tracking

The framework tracks two output channels across steps:

```
                   last_dataset_output                  last_model_output
                   (BQ table ref or URI)                (model resource name)
                          |                                    |
  +-------+         +----+----+         +-------+        +----+----+        +--------+
  |BQQuery|-------->|BQTrans  |-------->| Train |------->|Register |------->| Deploy |
  +-------+         +---------+         +---+---+        +----+----+        +---+----+
       |                 |                  |                  |                 |
       v                 v                  v                  v                 v
  destination_table  output_table     output_uri          output_uri        (reads from
  known at           known at         (model GCS path)    (resource name)    Model Registry
  compile time       compile time     runtime KFP         runtime KFP        by display_name)
                                      artifact             artifact
```

### @task Outputs (Compile-Time Deterministic)

`SmartCompiler._compute_task_output()` reads `destination_table` or `output_table` from the component and constructs a fully-qualified BQ reference: `{gcp_project}.{bq_dataset}.{table}`.

This is wired into the `RunPipelineJobOperator.parameter_values` as `dataset_uri`.

### @ml_task Outputs (Runtime KFP Artifacts)

Inside the KFP pipeline (`PipelineCompiler._build_kfp_pipeline()`):

```python
# After each step executes:
if component_fn.component_spec.outputs:
    task_output = task.outputs["output_uri"]
    if isinstance(step.component, (TrainModel, RegisterModel)):
        last_model_output = task_output     # -> wired to next step's model_uri
    elif not isinstance(step.component, WriteFeatures):
        last_dataset_output = task_output   # -> wired to next step's dataset_uri
```

**Key rule:** `WriteFeatures` is metadata-only and does NOT overwrite `last_dataset_output`.

### Bridging @task to @ml_task

When a `TASK` group precedes an `ML_TASK` group:

```
SmartCompiler._render_ml_group():
  bridged_params = {}
  if last_dataset_output:
      bridged_params["dataset_uri"] = last_dataset_output  # BQ table ref from BQQuery/BQTransform

  -> RunPipelineJobOperator(
       parameter_values={"run_date": "{{ ds }}", "dataset_uri": "<bq_ref>"},
     )
```

The KFP pipeline receives `dataset_uri` as a pipeline input parameter, which flows to the first ML step that accepts it.

---

## 10. Model Lifecycle

**Source:** `gcp_ml_framework/components/ml/train.py`, `evaluate.py`, `register.py`, `deploy.py`, `gcp_ml_framework/utils/vertex.py`, `gcp_ml_framework/utils/evaluate.py`

### End-to-End Flow

```
+----------+     +----------+     +----------+     +----------+     +----------+
|  Train   |---->| Evaluate |---->| Register |---->|  Deploy  |---->|  Serve   |
|          |     |          |     |          |     |          |     |          |
| run()    |     | run()    |     | run()    |     | run()    |     | /predict |
| -> model |     | -> metrics|    | -> Model |     | -> Endpt |     | /health  |
|    .pkl  |     |    + gates|    |    Registry|   |    deploy|    |          |
+----+-----+     +----+-----+     +----+-----+     +----+-----+     +----------+
     |                |                |                |
     v                v                v                v
  GCS: model/      output_uri:     Vertex AI        Vertex AI
  model.pkl        metrics JSON    Model Registry   Endpoint
```

### TrainModel (`components/ml/train.py`)

`execute()` lifecycle:
1. Calls `self.run()` -- data scientist returns local artifact path
2. Walks artifact directory, uploads all files to `{model_output_uri}/[{run_id}/]` via GCS
3. Writes `model_output_uri` to `output_uri_path` (KFP output artifact)
4. Best-effort experiment tracking via `aiplatform.log_params()`

**Note:** Experiment tracking code is currently dead code after `raise NotImplementedError` in `run()` (Bug 2). Should be moved into `execute()`.

### EvaluateModel (`components/ml/evaluate.py`)

`execute()` lifecycle:
1. Calls `self.run()` which delegates to `utils/evaluate.py:run_evaluate()`
2. Downloads `model.pkl` from GCS
3. Reads eval dataset from BigQuery
4. Auto-detects model type (classification vs regression) via `predict_proba`
5. Computes requested metrics
6. Applies metric gates
7. Best-effort experiment metric logging

### Metric Gates (Direction-Aware)

Defined in `gcp_ml_framework/utils/evaluate.py`:

| Metric | Direction | Gate Logic |
|--------|-----------|------------|
| `auc` | higher-is-better | Fail if `computed < threshold` |
| `f1` | higher-is-better | Fail if `computed < threshold` |
| `r2` | higher-is-better | Fail if `computed < threshold` |
| `rmse` | lower-is-better | Fail if `computed > threshold` |
| `mae` | lower-is-better | Fail if `computed > threshold` |
| `mse` | lower-is-better | Fail if `computed > threshold` |

The `regression_lower_is_better` set in `run_evaluate()`: `{"rmse", "mae", "mse"}`.

Gate failure raises `ValueError`, which halts the KFP pipeline.

### RegisterModel (`components/ml/register.py`)

**DESIGN LAW (PR #26):** RegisterModel is the **SINGLE OWNER** of the serving container image. No other component should specify or resolve serving images.

Model versioning logic:
1. Lists existing models by `display_name` filter
2. If found: creates a **new version** under the existing parent model (`parent_model=existing[0].resource_name`, `is_default_version=True`)
3. If not found: creates a new parent model (v1)
4. Writes the model's `resource_name` to `output_uri_path`

### Serving Container Resolution (Three-Tier Priority)

Resolved in `PipelineCompiler._build_derived_params()` for `RegisterModel`:

```
Priority 1: serving_container_image (full URI)
  -> Use as-is. For external images (e.g., Google pre-built CPR).
  Example: "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest"

Priority 2: serving_dockerfile (path relative to docker/)
  -> Resolved via NamingConvention.docker_image_uri()
  Example: "pipelines/house_price/serve.Dockerfile"
           -> "us-east4-docker.pkg.dev/proj/dsci-gcpdemo/house-price--serve:branch-sha"

Priority 3: Neither set
  -> Falls back to the pipeline's base image (runtime_dockerfile)
  -> Image name: "train"
```

### sync=False Design (PR #26 docs/register.md)

`Model.upload()` should use `sync=False` to avoid CRUD quota exhaustion on shared GCP projects. When `sync=True` (default), the SDK polls the LRO via repeated `GetOperation` calls, consuming the 600 req/min CRUD quota and causing `429 ResourceExhausted` errors.

**Current state:** PR #26 removed `sync=False` from the code, but the docs still document it as the design intent. This is a doc-code discrepancy -- the code should re-add `sync=False` to align with the documented design.

### DeployModel (`components/ml/deploy.py`)

**DESIGN LAW (PR #26):** `DeployModel` has **NO** serving image fields. It is a pure deployment concern -- find the model, find the endpoint, deploy. The serving image is already captured in the Model Registry by `RegisterModel`.

Delegates to `gcp_ml_framework/utils/vertex.py:run_deploy()`:
1. Looks up registered model by `model_display_name` (derived from `model_name` via naming convention)
2. Gets or creates endpoint by `endpoint_display_name` (derived from `model_name` via naming convention)
3. Deploys model to endpoint with traffic split, replica config
4. Optional: creates `ModelDeploymentMonitoringJob` with skew/drift thresholds

`model_name` is the **contract** between `RegisterModel` and `DeployModel`. Both must use
the same value so the compiler derives matching `model_display_name` and `endpoint_display_name`.

### Serving

Per-pipeline FastAPI applications at `app/{pipeline}/app.py`:

**Example** (`app/house_price/app.py`):
- FastAPI application with Pydantic request/response validation
- Vertex AI custom container protocol:
  - `GET /health` -> liveness check (returns 503 until model loaded)
  - `POST /predict` -> prediction (returns `{"predictions": [...]}`)
  - Listens on `AIP_HTTP_PORT` (default 8080)
- Loads model from `AIP_STORAGE_URI` at startup
- Used by `docker/pipelines/house_price/serve.Dockerfile`

**Note:** The generic handler (`gcp_ml_framework/serving/handler.py`) is a legacy
alternative using stdlib `http.server`. Per-pipeline FastAPI apps are the client's
recommended pattern (PR #26 `docs/deploy.md`).

---

## 11. Branch Isolation

### Namespace Isolation Model

Every branch gets its own namespace: `{team}-{project}-{branch}`.

| Resource | Scope | Isolation |
|----------|-------|-----------|
| BQ dataset | `{team}_{project}_{branch}` | Branch-scoped: each branch has its own dataset |
| GCS prefix | `gs://{bucket}/{branch}/` | Branch-scoped: objects namespaced under branch |
| GCS bucket | `{gcp_project}-{team}-{project}` | **Shared**: all branches share the same bucket |
| AR repo | `{team}-{project}` | **Shared**: images differentiated by tag `{branch}-{sha}` |
| DAG ID | `{namespace_bq}__{pipeline}` | Branch-scoped: unique DAG per branch |
| Vertex experiment | `{namespace}-{pipeline}-exp` | Branch-scoped |
| Vertex model | `{namespace}-{pipeline}[-{model}]` | Branch-scoped display name |
| Vertex endpoint | `{namespace}-{pipeline}-endpoint` | Branch-scoped display name |
| Feature Store | `{team}_{project}` | **Shared** store; feature views are branch-scoped |
| Feature view | `{entity}_{group}_{branch}` | Branch-scoped |
| Secret name | `{namespace}-{key}` | Branch-scoped |

### Teardown Scope

`gml teardown --branch <branch>` deletes:

1. **Composer DAG files** from GCS bucket (files matching `{namespace_bq}__*`)
2. **Airflow metadata** for each deleted DAG (`gcloud composer environments run ... dags delete`)
3. **GCS objects** under `gs://{bucket}/{branch}/`
4. **BQ dataset** `{team}_{project}_{branch}`

Safety guards (from `cmd_teardown.py`):
- Only allowed for DEV branches (blocks STAGING, PROD, EXPERIMENT)
- Requires `--confirm` flag or interactive Y/N prompt

---

## 12. CLI Command Reference

**Source:** `gcp_ml_framework/cli/main.py` and `cmd_*.py` files

Entry point: `gml` (registered in `pyproject.toml` as `gcp_ml_framework.cli.main:app`)

| Command | Source File | Purpose |
|---------|------------|---------|
| `gml init project <team> <project>` | `cli/cmd_init.py` | Scaffold new project (`.env`, CI/CD workflows, directories) |
| `gml init pipeline <name>` | `cli/cmd_init.py` | Scaffold new pipeline (`pipeline.py`, `config.yaml`, SQL templates) |
| `gml context show` | `cli/cmd_context.py` | Display resolved namespace, GCP project, all derived resource names |
| `gml compile <name>` | `cli/cmd_compile.py` | Compile pipeline to KFP YAML + Airflow DAG |
| `gml compile --all` | `cli/cmd_compile.py` | Compile all pipelines in `pipelines/` |
| `gml build <name>` | `cli/cmd_build.py` | Build Docker images via Cloud Build |
| `gml build --all` | `cli/cmd_build.py` | Build all pipeline images |
| `gml deploy <name>` | `cli/cmd_deploy.py` | Compile + upload DAGs to Composer + YAMLs to GCS + verify images |
| `gml deploy --all` | `cli/cmd_deploy.py` | Deploy all pipelines + feature schemas |
| `gml run <name>` | `cli/cmd_run.py` | Trigger deployed DAG in Composer |
| `gml run <name> --local` | `cli/cmd_run.py` | Execute pipeline in-process against real GCP dev resources |
| `gml run --all --local` | `cli/cmd_run.py` | Run all pipelines locally |
| `gml teardown --branch <b>` | `cli/cmd_teardown.py` | Delete all DEV resources for a branch namespace |
| `gml teardown --branch <b> --dry-run` | `cli/cmd_teardown.py` | Preview what would be deleted |

### Common Options

| Option | Commands | Purpose |
|--------|----------|---------|
| `--all` | compile, build, deploy, run | Operate on all pipelines |
| `--pipelines-dir` | compile, build, deploy, run | Override pipelines directory (default: `pipelines/`) |
| `--out` | compile, deploy | Override compiled YAML output directory (default: `compiled_pipelines/`) |
| `--dags-dir` | compile, deploy | Override DAG output directory (default: `dags/`) |
| `--dry-run` | deploy, teardown | Preview without executing |
| `--run-date` | run (--local only) | Override run_date (default: today) |
| `--branch` | context show, teardown | Override git branch |

---

## 13. Process Flows

### `gml compile <name>`

```
1. load_context()
   - load_config() merges: config.yaml + env vars + overrides
   - MLContext.from_config(cfg) builds NamingConvention
2. _discover_targets() finds pipeline directory
3. load_pipeline() imports pipeline.py, extracts `pipeline` variable (PipelineDefinition)
4. SmartCompiler.compile():
   a. _group_steps(): split into consecutive same-type groups
   b. For each ML_TASK group: PipelineCompiler.compile()
      - _build_kfp_pipeline(): construct @dsl.pipeline function
      - kfp.compiler.Compiler().compile() -> compiled_pipelines/{name}.yaml
   c. _generate_dag(): render Airflow DAG Python file
      - For TASK groups: component.render_operator()
      - For ML_TASK groups: RunPipelineJobOperator block
      - Sequential >> dependencies
      - Write to dags/{dag_id}.py
5. Print paths to generated artifacts
```

### `gml build <name>`

```
1. load_context()
2. build_command() constructs gcloud command:
   - gcloud builds submit --config cloudbuild.yaml
   - --substitutions _TAG={branch}-{sha},_PIPELINE={slug},_AR_REPO={ar_repo}
   - --service-account {pipeline_sa}
3. subprocess.run(cmd)
4. Cloud Build executes cloudbuild.yaml:
   a. Pull cached base-python:latest
   b. Build + push base-python:{tag} + :latest
   c. Build + push per-pipeline images (base + serve)
```

### `gml deploy <name>`

```
1. load_context()
2. Compile first (calls compile_cmd internally)
3. _ensure_images(): scan compiled YAMLs for image URIs
   - For each image: verify it exists in AR via ensure_image_tag()
   - If tag missing: find same image with any branch-matching tag, re-tag
4. _upload_dags(): for each .py in dags/ matching the pipeline name
   - upload_file(dag_file, {composer_dags_path}/{filename})
5. _upload_pipeline_yamls(): for each .yaml in compiled_pipelines/
   - upload_file(yaml_file, gs://{bucket}/{branch}/pipelines/{stem}/pipeline.yaml)
6. _deploy_features() (only with --all): load + deploy feature schemas
```

### `gml run --local <name>`

```
1. load_context()
2. load_pipeline(pipeline_dir) -> PipelineDefinition
3. LocalRunner.run(pipeline_def, context, run_date):
   a. Build ctx_params (same as PipelineCompiler)
   b. Build derived_params (same as PipelineCompiler)
   c. For each step:
      - Merge: component_fields + ctx_params + derived_params
      - Wire cross-step: last_dataset_output -> dataset_uri, last_model_output -> model_uri
      - Inject run_date
      - Filter to accepted fields
      - Instantiate fresh component with merged params
      - Call component.execute() directly (no container)
      - Track outputs for next step
```

### `gml run <name>` (Composer)

```
1. load_context()
2. Construct gcloud command:
   gcloud composer environments run {env_name}
     --location {region} --project {project}
     dags trigger -- {dag_id}
3. subprocess.run(cmd)
4. Composer parses DAG, schedules tasks
```

### Container Execution (inside KFP)

```
1. KFP starts container with: python -m {step_module} --flag1 val1 --flag2 val2
2. Component.__main__ calls ComponentClass.cli()
3. cli():
   a. Typer auto-generates --flag per Pydantic field (excluding _INTERNAL_FIELDS)
   b. Parse CLI args into kwargs
   c. JSON-decode any string values starting with { or [
   d. Instantiate component with kwargs
   e. Call component.execute()
4. execute() runs I/O lifecycle + calls run()
5. run() executes data scientist business logic
```

### Serving (Vertex AI Endpoint)

```
1. Vertex AI starts container with AIP_STORAGE_URI, AIP_HTTP_PORT env vars
2. On startup: download model.pkl from AIP_STORAGE_URI (GCS)
3. Unpickle model into memory
4. Listen on AIP_HTTP_PORT (default 8080)
5. POST /predict: deserialize instances -> model.predict(df) -> return predictions
6. GET /health: return {"status": "healthy"}
```

---

## 14. Design Decisions and Trade-offs

### Why `container_component` over `component`

KFP offers two component types: `@component` (which bundles code into the YAML) and `@container_component` (which points to a pre-built Docker image).

The framework uses `@container_component` because:
- Data scientists bring their own dependencies (scikit-learn, xgboost, etc.) -- these are baked into the Docker image
- The entire framework and pipeline code is available inside the container
- Each component becomes a CLI entrypoint (`python -m {module}`) with auto-generated `--flag` per field
- Pydantic field types are serialized as strings, keeping KFP I/O simple

**Trade-off:** Requires Docker image builds before pipeline submission. `gml build` handles this.

### Why generated DAGs have zero framework imports

Generated DAG files in `dags/` are **self-contained Python**. They import only standard Airflow operators and providers:

```python
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.providers.google.cloud.operators.vertex_ai.pipeline_job import RunPipelineJobOperator
```

This design means:
- The `gcp_ml_framework` package does NOT need to be installed on Composer workers
- DAG parsing is fast (no heavy framework imports)
- DAG files are portable -- copy them to any Airflow environment
- No risk of version conflicts between framework and Airflow environment

**Trade-off:** All template variables (SQL, subjects, etc.) must be resolved at compile time. Airflow macros (`{{ ds }}`) are injected as literal strings.

### Why a single NamingConvention

All GCP resource names flow through `NamingConvention` in `naming.py`. This single source of truth prevents name drift between:
- Python framework (compiler, runner, deploy)
- Bash scripts (docker_build.sh)
- Terraform (uses the same `{team}-{project}` pattern for bucket and AR repo names)
- CLI commands (teardown must match the names created by deploy)

The alternative -- constructing names ad-hoc across the codebase -- would lead to mismatches when any convention changes.

### Why `enable_caching=False`

`RunPipelineJobOperator` in generated DAGs sets `enable_caching=False`. This overrides KFP's per-step `enableCache: true` in the YAML.

**Root cause:** After `gml teardown` deletes BQ tables and GCS objects, cached pipeline steps would return stale URIs pointing to deleted resources, causing downstream failures.

**Trade-off:** Every pipeline run re-executes all steps (no cache hits). For most ML pipelines this is the correct behavior -- you want fresh data on each scheduled run.

**Note:** `base.py:57` (`cache_enabled: bool = True`) and `runner.py:29` (`enable_caching: bool = True`) still default to `True`, contradicting this design. Both should default to `False`.

### Why 2-tier Docker Hierarchy (Per Client PR #26)

```
base-python (Tier 0) -> per-pipeline base + serve (Tier 1)
```

**Tier 0 (base-python):** Changes rarely (Python version, system packages). Tagged `:latest` only. Built separately via `docker_build_base.sh`. Shared across all projects.

**Tier 1 (per-pipeline):** Two Dockerfiles per pipeline:
- `base.Dockerfile`: Extends `base-python`. Contains the framework, all dependencies, pipeline code, and estimator module. Used for training, evaluation, registration, and deployment steps (`runtime_dockerfile`).
- `serve.Dockerfile`: Extends the pipeline base image. Adds FastAPI + uvicorn + the serving app. Used for Vertex AI endpoint serving (`serving_dockerfile`).

Root-level default Dockerfiles (`docker/train.Dockerfile`, `docker/serve.Dockerfile`) are **removed** per client PR #26. Every pipeline explicitly declares its own Dockerfiles.

**Trade-off:** Each new pipeline requires creating its own Dockerfile pair. This is intentional -- it forces pipeline authors to be explicit about their dependencies and serving setup, avoiding hidden defaults.

### Why SQL template variables instead of Jinja

Components like `BQQuery` use framework template variables (`{bq_dataset}`, `{run_date}`) rather than Jinja:

```sql
SELECT * FROM `{bq_dataset}.raw_events` WHERE date = '{run_date}'
```

At compile time:
- `{bq_dataset}` is replaced with the resolved dataset name
- `{run_date}` is replaced with `{{ ds }}` (Airflow Jinja macro)

This two-pass approach keeps pipeline definitions framework-agnostic while ensuring Airflow macros work correctly at runtime.

### Why `BaseComponent` extends `BaseSettings`

Using Pydantic's `BaseSettings` (not `BaseModel`) means component fields are automatically populated from environment variables when running inside containers. Combined with the CLI auto-generation in `cli()`, this gives three ways to configure a component:
1. Constructor kwargs (in `pipeline.py`)
2. Environment variables (in the container)
3. CLI flags (auto-generated by Typer)

### GCP Best Practices Assessment

**Following:**
- `RunPipelineJobOperator` (correct, not `CreatePipelineJobOperator`)
- `template_fields` extension for Jinja rendering in generated DAGs
- Artifact Registry (not deprecated Container Registry)
- Cloud Build with layer caching (`--cache-from` pattern)
- Feature Store v2 (BQ-native) with `v1beta1` for FeatureGroup
- BigQuery v3.25+ (modern jobs API)
- `google-cloud-aiplatform>=1.136`
- GCS bucket naming with project ID for global uniqueness
- Branch-isolated GCS prefixes for multi-tenant safety
- Service account impersonation pattern in Composer

**Gaps to Address:**
- No uniform bucket-level access configured (GCS ACL simplification)
- No lifecycle rules on GCS (old pipeline artifacts accumulate indefinitely)
- No AR cleanup/vulnerability scanning policies (image sprawl)
- Secret Manager client lacks response caching (repeated lookups)
- AR operations use `subprocess`/`gcloud` CLI instead of `google-cloud-artifactregistry` SDK
- Generic `Exception` catching throughout (should catch `google.api_core.exceptions.NotFound` etc.)
- `enable_caching` defaults wrong in `base.py` and `runner.py` (True instead of False)
- `cloudbuild.yaml` references legacy Dockerfiles (`docker/pipeline/Dockerfile`, `docker/serving/Dockerfile`)
