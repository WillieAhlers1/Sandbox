# GCP ML Framework — Complete Walkthrough

> Everything you need to know: every DSL, component, CLI command, configuration option, and workflow.

---

## What This Is

A Python library + CLI (`gml`) that lets data scientists define ML pipelines and data workflows as Python code, run them locally with zero GCP cost, and deploy them to Google Cloud Platform.

The key idea: your git branch determines your GCP namespace. Every resource — BigQuery datasets, GCS paths, Vertex AI experiments, Composer DAGs, Feature Store views — is automatically scoped to `{team}-{project}-{branch}`. No hardcoded project IDs. No `if env == "prod"`. No resource collisions between branches.

**Codebase stats:**
- 51 Python source files, ~4,700 lines of framework code
- 19 test files, ~3,500 lines, 359 tests (all passing)
- 4 working example pipelines with seed data
- Full CLI with 6 command groups
- 4 Terraform modules for infrastructure

---

## Setup

```bash
# Install uv (Python package manager) if you don't have it
pip install uv

# Install all dependencies from lockfile
uv sync

# Verify the CLI works
uv run gml --help
```

All commands below use `uv run gml` because the CLI is installed as a project script. If you have the virtualenv activated, plain `gml` works too.

---

## The Two DSLs

The framework has two separate DSLs for two different levels of orchestration:

### 1. PipelineBuilder — ML Pipelines (Vertex AI)

For ML workflows that run as a single Vertex AI Pipeline. Each step is a KFP v2 component. Steps execute sequentially with automatic cross-step data wiring.

```
pipeline.py -> PipelineBuilder -> PipelineDefinition
    -> PipelineCompiler -> KFP v2 YAML -> Vertex AI Pipelines
    -> LocalRunner -> DuckDB stubs (no GCP)
```

**File:** `pipelines/{name}/pipeline.py`

**What it looks like** (from `pipelines/churn_prediction/pipeline.py`):

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(
        query="SELECT * FROM `{bq_dataset}.raw_user_events` WHERE ...",
        output_table="churn_training_raw",
    ), name="ingest_raw_events")
    .transform(BQTransform(
        sql="SELECT *, SAFE_DIVIDE(...) AS trend FROM `{bq_dataset}.churn_training_raw`",
        output_table="churn_features_engineered",
    ), name="engineer_features")
    .write_features(WriteFeatures(
        entity="user", feature_group="behavioral", entity_id_column="user_id",
    ), name="write_user_features")
    .train(TrainModel(
        machine_type="n2-standard-8",
        hyperparameters={"learning_rate": 0.05, "max_depth": 6},
    ), name="train_churn_model")
    .evaluate(EvaluateModel(
        metrics=["auc", "f1"], gate={"auc": 0.78},
    ), name="evaluate_model")
    .deploy(DeployModel(
        endpoint_name="churn-classifier",
        serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest",
    ), name="deploy_churn_model")
    .build()
)
```

**Available components:**

| Stage | Component | What It Does |
|---|---|---|
| `.ingest()` | `BigQueryExtract` | Run BQ SQL query, export results to GCS as Parquet |
| `.ingest()` | `GCSExtract` | Copy files from a GCS source path to branch staging prefix |
| `.transform()` | `BQTransform` | Run SQL transformation (inline or from file), materialize to BQ table |
| `.write_features()` | `WriteFeatures` | Register BQ table as a Feature Store v2 FeatureGroup (metadata only, no data movement) |
| `.read_features()` | `ReadFeatures` | Read features from Feature Store (offline from BQ, online from Bigtable) |
| `.train()` | `TrainModel` | Submit Vertex AI Custom Training Job with versioned model output path |
| `.evaluate()` | `EvaluateModel` | Compute metrics (AUC, F1) + quality gates (halt pipeline if threshold not met) |
| `.deploy()` | `DeployModel` | Upload model to registry, deploy to Endpoint with canary traffic split |

Template variables like `{bq_dataset}`, `{run_date}`, `{gcs_prefix}`, `{artifact_registry}` are auto-resolved from your git branch context.

### 2. DAGBuilder — Composer DAGs (Airflow)

For orchestration workflows that run on Cloud Composer. Can include BQ queries, Vertex pipelines, notifications — anything Airflow supports. Supports explicit `depends_on` for parallel tasks and fan-in patterns.

```
dag.py -> DAGBuilder -> DAGDefinition
    -> DAGCompiler -> standalone Airflow DAG Python file -> Composer GCS bucket
    -> DAGLocalRunner -> DuckDB stubs + console output (no GCP)
```

**File:** `pipelines/{name}/dag.py`

**Simple ETL** (from `pipelines/daily_sales_etl/dag.py`):

```python
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(name="daily_sales_etl", schedule="30 7 * * *", tags=["etl", "sales"])
    .task(BQQueryTask(sql="SELECT ...", destination_table="staged_orders"), name="extract")
    .task(BQQueryTask(sql="SELECT ...", destination_table="summary"), name="transform")
    .task(EmailTask(to=["team@co.com"], subject="[{namespace}] ETL Complete"), name="notify")
    .build()
)
```

**Fan-out/fan-in** (from `pipelines/sales_analytics/dag.py`):

```python
dag = (
    DAGBuilder(name="sales_analytics", schedule="0 8 * * *")
    # 3 parallel extractions (depends_on=[] = no upstream dependency)
    .task(BQQueryTask(sql_file="sql/extract_orders.sql", destination_table="staged_orders"),
          name="extract_orders", depends_on=[])
    .task(BQQueryTask(sql_file="sql/extract_inventory.sql", destination_table="staged_inventory"),
          name="extract_inventory", depends_on=[])
    .task(BQQueryTask(sql_file="sql/extract_returns.sql", destination_table="staged_returns"),
          name="extract_returns", depends_on=[])
    # 3 aggregations, each depends on its extraction
    .task(BQQueryTask(sql_file="sql/agg_revenue.sql", destination_table="agg_revenue"),
          name="agg_revenue", depends_on=["extract_orders"])
    .task(BQQueryTask(sql_file="sql/check_stock.sql", destination_table="stock_status"),
          name="check_stock", depends_on=["extract_inventory"])
    .task(BQQueryTask(sql_file="sql/agg_refunds.sql", destination_table="agg_refunds"),
          name="agg_refunds", depends_on=["extract_returns"])
    # Fan-in: report depends on all aggregations
    .task(BQQueryTask(sql_file="sql/build_report.sql", destination_table="daily_report"),
          name="build_report", depends_on=["agg_revenue", "check_stock", "agg_refunds"])
    .task(EmailTask(to=["analytics-team@co.com"], subject="Report ready"), name="notify")
    .build()
)
```

**Hybrid (Vertex pipelines inside a DAG)** (from `pipelines/recommendation_engine/dag.py`):

```python
dag = (
    DAGBuilder(name="recommendation_engine", schedule="0 4 * * *")
    .task(BQQueryTask(sql_file="sql/extract_interactions.sql", destination_table="staged_interactions"),
          name="extract_interactions", depends_on=[])
    .task(VertexPipelineTask(pipeline_name="reco_features"),
          name="run_feature_pipeline", depends_on=["extract_interactions"])
    .task(VertexPipelineTask(pipeline_name="reco_training"),
          name="run_training_pipeline", depends_on=["extract_interactions"])
    .task(EmailTask(to=["ml-team@co.com"], subject="Reco engine complete"),
          name="notify", depends_on=["run_feature_pipeline", "run_training_pipeline"])
    .build()
)
```

**Available task types:**

| Task | Airflow Operator | Purpose |
|---|---|---|
| `BQQueryTask` | `BigQueryInsertJobOperator` | Run SQL (inline or from file) with template variables |
| `VertexPipelineTask` | Custom operator | Submit a compiled Vertex AI Pipeline |
| `EmailTask` | `EmailOperator` | Send notifications with template variables |

**Key differences from PipelineBuilder:**
- DAGBuilder supports explicit `depends_on` for parallel tasks and fan-in patterns
- DAGBuilder compiles to a static Python file (no framework dependency at Airflow parse time)
- PipelineBuilder steps are always sequential; DAGBuilder tasks can be parallel
- DAGBuilder can embed VertexPipelineTasks for hybrid ML+orchestration workflows

---

## Every CLI Command

### `gml context show` — See Your Resolved Namespace

Shows what GCP resources the framework will target based on your current git branch.

```bash
uv run gml context show
uv run gml context show --branch main        # override branch
uv run gml context show --json               # machine-readable output
```

Output:
```
GCP ML Framework — context for branch 'feature/user-embeddings'

               Identity
  team             dsci
  project          examplechurn
  branch (raw)     feature/user-embeddings
  branch (slug)    feature-user-embeddings
  git_state        DEV

                GCP
  project         gcp-gap-demo-dev
  region          us-central1

                                 Resource Names
  namespace                    dsci-examplechurn-feature-user-embeddings
  gcs_bucket                   dsci-examplechurn
  gcs_prefix                   gs://dsci-examplechurn/feature-user-embeddings/
  bq_dataset                   dsci_examplechurn_feature_user_embe
  feature_store_id             dsci_examplechurn
  dag_id pattern               dsci_examplechurn_feature_user_embe__{pipeline}
  secret_prefix                dsci-examplechurn-feature-user-embeddings
```

### `gml run` — Execute a Pipeline

**Local run (default — no GCP needed):**

```bash
uv run gml run churn_prediction --local             # full local execution with DuckDB
uv run gml run churn_prediction --local --dry-run    # print execution plan only
uv run gml run sales_analytics --local               # works for DAG-based pipelines too
```

**How local run works:**
1. Seeds DuckDB from CSV/Parquet files in `pipelines/{name}/seeds/`
2. For pipeline.py: calls each component's `local_run()` sequentially
3. For dag.py: executes tasks in topological order via `DAGLocalRunner`
4. BigQueryExtract/BQTransform use DuckDB with BQ-to-DuckDB SQL translation
5. VertexPipelineTasks run their contained pipeline via nested `LocalRunner` with shared DuckDB connection
6. TrainModel writes a placeholder model JSON
7. EvaluateModel returns placeholder metrics (0.50 for all)
8. DeployModel prints a stub endpoint name
9. EmailTask prints to console

**Vertex AI run (requires GCP credentials):**

```bash
uv run gml run churn_prediction --vertex              # async — returns immediately
uv run gml run churn_prediction --vertex --sync       # wait for completion
uv run gml run --vertex --all                         # run all pipelines
uv run gml run churn_prediction --vertex --no-cache   # disable KFP step caching
```

### `gml compile` — Compile to Deployable Artifacts

```bash
uv run gml compile churn_prediction     # one pipeline
uv run gml compile --all               # all pipelines
```

For `pipeline.py`: generates KFP v2 YAML + auto-wrapped Airflow DAG file.
For `dag.py`: generates standalone Airflow DAG file + compiles any embedded VertexPipelineTasks.

### `gml deploy` — Compile and Upload

```bash
uv run gml deploy churn_prediction          # compile + upload one pipeline
uv run gml deploy --all                     # compile + upload everything
uv run gml deploy --all --dry-run           # preview what would be deployed
```

Uploads:
1. DAG files to Composer GCS bucket
2. Compiled pipeline YAMLs to GCS
3. Feature schemas to Feature Store (with `--all`)

### `gml init` — Scaffold New Projects and Pipelines

```bash
# Scaffold a brand new project
uv run gml init project dsci churn-pred \
  --dev-project my-gcp-dev \
  --staging-project my-gcp-staging \
  --prod-project my-gcp-prod

# Add a new pipeline to an existing project
uv run gml init pipeline my_new_pipeline
```

`init project` creates: `framework.yaml`, `feature_schemas/`, `pipelines/`, `dags/`, `.github/workflows/` (4 CI/CD workflow files), `tests/`, `.python-version`, `.gitignore`.

`init pipeline` creates: `pipelines/{name}/pipeline.py` (with template), `config.yaml`, `sql/{name}_features.sql`.

### `gml teardown` — Delete Ephemeral DEV Resources

```bash
uv run gml teardown --branch feature/my-experiment --dry-run   # preview
uv run gml teardown --branch feature/my-experiment --confirm   # skip confirmation
```

Safety: refuses to teardown STAGING or PROD. Only DEV branches.

Deletes: GCS prefix, BQ dataset.

---

## Component Reference

### BigQueryExtract

Run a SQL query and export results to GCS as Parquet.

```python
BigQueryExtract(
    query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
    output_table="raw_events_extract",
    write_disposition="WRITE_TRUNCATE",  # default
)
```

Template variables: `{bq_dataset}`, `{gcs_prefix}`, `{run_date}`.

**Local run:** Executes SQL on DuckDB with automatic BQ-to-DuckDB translation (backticks, `DATE_SUB`, `SAFE_DIVIDE`, `LOG1P`, `CURRENT_TIMESTAMP`, `FLOAT64`).

### GCSExtract

Copy files from a GCS source path to the branch staging prefix.

```python
GCSExtract(
    source_uri="gs://data-lake/raw/events/*.parquet",
    destination_folder="raw_events",
)
```

**Local run:** Creates an empty temp directory (placeholder).

### BQTransform

Run a SQL transformation and materialize to a BQ table. Supports inline SQL or SQL file.

```python
# Inline SQL
BQTransform(sql="SELECT *, LOG1P(purchases) AS log_purchases FROM `{bq_dataset}.raw`", output_table="features")

# SQL file (relative to pipeline directory)
BQTransform(sql_file="sql/features.sql", output_table="features")
```

Validation: requires either `sql` or `sql_file` (raises `ValueError` otherwise).

**Local run:** Executes on DuckDB with BQ-to-DuckDB SQL translation.

### WriteFeatures

Register a BQ table as a Vertex AI Feature Store v2 FeatureGroup. Metadata-only operation — no data movement.

```python
WriteFeatures(
    entity="user",
    feature_group="behavioral",
    entity_id_column="user_id",
    feature_time_column="feature_timestamp",  # default
    feature_ids=["session_count_7d", "purchases_30d"],  # empty = all
)
```

Uses `FeatureRegistryServiceClient` to create or get the FeatureGroup.

### ReadFeatures

Read feature values from Feature Store. Offline: reads from BQ source table. Online: reads from Bigtable.

```python
ReadFeatures(
    entity="user",
    feature_group="behavioral",
    feature_ids=["session_count_7d"],  # empty = all
    output_table="features_read",      # default
)
```

**Local run:** Reads from DuckDB via shared `db_conn`. Falls back to empty DataFrame if table not found.

### TrainModel

Submit a Vertex AI Custom Training Job.

```python
TrainModel(
    trainer_image="us-central1-docker.pkg.dev/proj/repo/trainer:latest",  # optional — auto-resolved if empty
    machine_type="n2-standard-8",
    accelerator_type="NVIDIA_TESLA_T4",  # optional
    accelerator_count=1,                  # optional
    hyperparameters={"learning_rate": 0.05, "max_depth": 6},
    trainer_args=["--epochs=100"],        # additional CLI args
)
```

**Auto image resolution:** If `trainer_image` is empty, derives from pipeline name: `{registry}/{pipeline_slug}-trainer:latest`.

**Model versioning:** Artifacts stored at `{gcs_prefix}/models/{pipeline_name}/{run_id}/`.

**Local run:** Writes a placeholder `model.json` to a versioned temp directory.

### EvaluateModel

Compute metrics and apply quality gates.

```python
EvaluateModel(
    metrics=["auc", "f1"],
    gate={"auc": 0.78, "f1": 0.60},  # pipeline fails if any metric below threshold
)
```

**KFP component:** Downloads model from GCS, loads eval dataset from BQ, computes real sklearn metrics, logs to Vertex AI Experiments.

**Local run:** Returns placeholder metrics (0.50 for all). Gate logic still applies — if threshold > 0.50, the local run will fail (by design, to validate gate configuration).

### DeployModel

Upload model to Vertex AI Model Registry and deploy to an Endpoint.

```python
DeployModel(
    endpoint_name="churn-classifier",
    serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest",
    machine_type="n2-standard-2",
    min_replica_count=1,
    max_replica_count=3,
    traffic_split={"new": 10, "current": 90},  # canary deployment
)
```

Uses stable endpoint names derived from the namespace — URL never changes across releases.

---

## Branch Isolation

Your git branch determines everything:

| Git State | Environment | GCP Project | What Happens |
|---|---|---|---|
| `feature/*`, `hotfix/*`, any branch | DEV | `dev_project_id` | Ephemeral. Auto-cleanup on merge. |
| `main` | STAGING | `staging_project_id` | Persistent. Full integration testing. |
| Release tag `v*` | PROD | `prod_project_id` | Immutable. Promoted from STAGING only. |
| `prod/*` | PROD (Experiment) | `prod_project_id` | Controlled A/B experiments. |

When you're on `feature/user-embeddings`:

```
namespace:   dsci-examplechurn-feature-user-embeddings
GCS:         gs://dsci-examplechurn/feature-user-embeddings/
BigQuery:    dsci_examplechurn_feature_user_embe
Vertex:      dsci-examplechurn-feature-user-embeddings-churn_prediction
DAG ID:      dsci_examplechurn_feature_user_embe__churn_prediction
```

When you merge to `main`:

```
namespace:   dsci-examplechurn-main
GCS:         gs://dsci-examplechurn/main/
BigQuery:    dsci_examplechurn_main
```

No code changes needed. The framework reads your git branch and resolves everything automatically via `NamingConvention`.

---

## Config System

Config is resolved in this order (later wins):

```
framework defaults -> framework.yaml -> pipelines/{name}/config.yaml -> env vars -> CLI flags
```

**`framework.yaml`** (project root — single source of truth for team identity):
```yaml
team: dsci
project: examplechurn
gcp:
  dev_project_id: gcp-gap-demo-dev
  staging_project_id: gcp-gap-demo-staging
  prod_project_id: gcp-gap-demo-prod
  region: us-central1
  artifact_registry_host: us-central1-docker.pkg.dev
  composer_dags_path:
    dev: ""       # fill in after Terraform provisions Composer
    staging: ""
    prod: ""
```

**Environment variable overrides** (prefix `GML_`, nested via `__`):
```bash
GML_TEAM=dsci
GML_GCP__REGION=europe-west1
GML_ENV_OVERRIDE=staging    # force a specific environment
```

**Secrets** (referenced as `!secret key`, resolved at runtime):
```bash
# Local development — use env vars
export GML_SECRET_DB_URL="postgres://localhost/mydb"

# GCP — resolved from Secret Manager: {namespace}-{key}
```

---

## Example Pipelines

### 1. `pipelines/churn_prediction/` — Full ML Loop (PipelineBuilder)

Weekly churn model training and deployment pipeline. 6 steps, seed data, custom trainer.

```
ingest_raw_events (BigQueryExtract)
    -> engineer_features (BQTransform — SAFE_DIVIDE, LN, CURRENT_TIMESTAMP)
        -> write_user_features (WriteFeatures — 6 behavioral features)
            -> train_churn_model (TrainModel — sklearn LogisticRegression)
                -> evaluate_model (EvaluateModel — AUC gate >= 0.78)
                    -> deploy_churn_model (DeployModel — sklearn serving container)
```

**Seed data:** `seeds/raw_user_events.csv` — 10 users with session counts, purchase data, and churn labels.
**Trainer:** `trainer/train.py` — sklearn StandardScaler + LogisticRegression.

### 2. `pipelines/daily_sales_etl/` — Simple ETL DAG (DAGBuilder)

Daily extract, transform, notify. 3 tasks, linear.

```
extract_raw_orders (BQQueryTask) -> transform_daily_summary (BQQueryTask) -> notify_team (EmailTask)
```

**Seed data:** `seeds/raw_orders.csv` — 8 orders.

### 3. `pipelines/sales_analytics/` — Fan-out/Fan-in (DAGBuilder)

8-task non-linear DAG with 3 parallel extraction branches that fan-in to a report.

```
extract_orders     -> agg_revenue   -+
extract_inventory  -> check_stock   -+-> build_report -> notify
extract_returns    -> agg_refunds   -+
```

**Seed data:** 3 CSV files (orders, inventory, returns).
**SQL files:** 7 SQL files in `sql/` directory.

### 4. `pipelines/recommendation_engine/` — Hybrid DAG (DAGBuilder + Vertex)

BQ extraction feeding 2 parallel Vertex AI pipelines, then notification.

```
extract_interactions -> run_feature_pipeline (VertexPipelineTask: reco_features)
                     -> run_training_pipeline (VertexPipelineTask: reco_training)
                                                                    -> notify
```

**Sub-pipelines:** `reco_features/pipeline.py` (feature extraction) and `reco_training/pipeline.py` (model training with NMF collaborative filtering).
**Seed data:** `seeds/raw_interactions.csv`.

**Try any pipeline locally:**
```bash
uv run gml run churn_prediction --local
uv run gml run daily_sales_etl --local
uv run gml run sales_analytics --local
uv run gml run recommendation_engine --local
```

---

## Docker Automation

The framework provides base Docker images and auto-generation:

**Base images** (`docker/base/`):
- `base-python` — Python 3.11 slim
- `base-ml` — scikit-learn, pandas, numpy, xgboost on top of base-python

**Auto-generation** (`scripts/docker_build.sh`):
- Scans `pipelines/*/trainer/` for training scripts
- Auto-generates a Dockerfile if one doesn't exist
- Builds and optionally pushes to Artifact Registry

**TrainModel auto-resolution:** If `trainer_image` is left empty, the framework auto-derives the image URI from the pipeline name using `{registry}/{pipeline_slug}-trainer:latest`.

---

## Feature Store v2

Uses Vertex AI Feature Store v2 (BQ-native APIs):

**Entity schemas** (`feature_schemas/*.yaml`):
```yaml
entity: user
id_column: user_id
id_type: STRING
feature_groups:
  behavioral:
    description: "Behavioral engagement features"
    features:
      - name: session_count_7d
        type: INT64
      - name: total_purchases_30d
        type: FLOAT64
```

**API concepts:**
- **FeatureGroup** — registers a BQ table as a feature source (metadata only)
- **Feature** — individual columns within a FeatureGroup
- **FeatureOnlineStore** — Bigtable-backed online serving
- **FeatureView** — connects a FeatureGroup to a FeatureOnlineStore with sync

Feature views are branch-namespaced (e.g., `user_behavioral_main`) so DEV writes never overwrite PROD.

**Client usage:**
```python
from gcp_ml_framework.feature_store.client import FeatureStoreClient

client = FeatureStoreClient(context)
client.ensure_feature_group("user_behavioral", "project.dataset.table")
client.ensure_feature_view("user", "behavioral", "project.dataset.table")
```

---

## Infrastructure (Terraform)

Shared infrastructure is managed via Terraform modules in `terraform/`:

| Module | Resource | Purpose |
|---|---|---|
| `composer` | `google_composer_environment` | Cloud Composer 3 with workloads_config (scheduler, triggerer, dag_processor, web_server, worker) |
| `artifact_registry` | `google_artifact_registry_repository` | Docker repos for ML pipeline containers |
| `iam` | Service accounts + WIF | Composer SA (roles/composer.worker), Pipeline SA (roles/aiplatform.user), GitHub Actions OIDC |
| `storage` | `google_storage_bucket` | GCS buckets with versioning and uniform access |

Per-environment scaling:

| Environment | Size | Workers | Schedulers |
|---|---|---|---|
| dev | SMALL | 1-3 | 1 |
| staging | SMALL | 1-4 | 1 |
| prod | MEDIUM | 2-6 | 2 |

```bash
cd terraform/envs/dev
terraform init && terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

After provisioning, update `framework.yaml` with the Composer DAGs path from `terraform output composer_dags_path`.

---

## Running Tests

```bash
# Run all 359 tests
uv run pytest tests/ -v

# Unit tests only
uv run pytest tests/unit/ -v

# Integration tests only
uv run pytest tests/integration/ -v

# Specific test file
uv run pytest tests/unit/test_components.py

# With coverage
uv run pytest tests/ --cov=gcp_ml_framework --cov-report=term-missing

# Linting
uv run ruff check .

# Type checking
uv run mypy gcp_ml_framework/
```

**Test breakdown:**

| Test File | Tests | What It Covers |
|---|---|---|
| `test_components.py` | 44 | All 8 components: defaults, local_run() with DuckDB, as_kfp_component(), gate logic |
| `test_cli.py` | 22 | All 6 CLI commands: init, context, compile, run, deploy, teardown |
| `test_pipeline_builder.py` | 28 | PipelineBuilder DSL, step sequencing, KFP compilation, artifact registry resolution |
| `test_dag_builder.py` | 23 | DAGBuilder DSL, depends_on, topological sort, cycle detection, validation |
| `test_dag_compiler.py` | 15 | DAG file rendering, template resolution, Airflow macro conversion |
| `test_dag_tasks.py` | 29 | BQQueryTask, EmailTask, VertexPipelineTask, TaskConfig |
| `test_naming.py` | 23 | Namespace resolution, slugification, BQ naming, feature views, secret names |
| `test_config.py` | 13 | Git state resolution, environment mapping, config layering |
| `test_context.py` | 9 | MLContext creation, property delegation, production checks |
| `test_feature_schema.py` | 10 | YAML schema parsing, feature groups, entity schemas |
| `test_secrets.py` | 7 | Secret resolution, env var fallback, `!secret` dict resolution |
| `test_sql_compat.py` | 10 | BigQuery to DuckDB SQL translation (7 functions) |
| `test_phase1.py` | 35 | Phase 1 regression: dead code removal, machine types, CLI structure |
| `test_phase2.py` | 49 | Phase 2 regression: Docker, DAG runner, use cases, seed data |
| `test_phase3.py` | 18 | Phase 3 regression: Feature Store v2, model versioning, experiments |
| `test_e2e.py` (integration) | 24 | Full compile + local run for all 4 pipelines, generated DAG validation |

---

## Quick Reference: Common Workflows

```bash
# "I want to see what resources my branch would use"
uv run gml context show

# "I want to iterate on SQL locally"
uv run gml run my_pipeline --local

# "I want to validate my pipeline compiles"
uv run gml compile my_pipeline

# "I want to test on real GCP"
uv run gml run my_pipeline --vertex --sync

# "I want to generate Airflow DAGs"
uv run gml compile --all

# "I want to deploy everything"
uv run gml deploy --all

# "I want to run all tests"
uv run pytest tests/ -v

# "I want to add a new pipeline"
uv run gml init pipeline my_new_pipeline
# Then edit pipelines/my_new_pipeline/pipeline.py

# "I want to clean up my branch resources"
uv run gml teardown --branch feature/my-experiment --confirm

# "I want to see what Terraform would provision"
cd terraform/envs/dev && terraform plan -var-file=terraform.tfvars
```
