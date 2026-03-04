# Understanding the GCP ML Framework — Complete Walkthrough

> What we built, how it works, and how to use every piece of it.

---

## What This Is

A Python library + CLI (`gml`) that lets data scientists define ML pipelines and data workflows as Python code, run them locally with zero GCP cost, and deploy them to Google Cloud Platform.

The key idea: your git branch determines your GCP namespace. Every resource — BigQuery datasets, GCS paths, Vertex AI experiments, Composer DAGs — is automatically scoped to `{team}-{project}-{branch}`. No hardcoded project IDs. No `if env == "prod"`. No resource collisions between branches.

**Codebase stats:**
- 50 Python source files, ~4,400 lines of framework code
- 10 test files, ~1,300 lines, 167 unit tests (all passing)
- 2 working example pipelines with seed data
- Full CLI with 6 command groups

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

For ML workflows that run as a single Vertex AI Pipeline. Each step is a KFP v2 component.

```
pipeline.py → PipelineBuilder → PipelineDefinition
    → PipelineCompiler → KFP v2 YAML → Vertex AI Pipelines
    → LocalRunner → DuckDB stubs (no GCP)
```

**File:** `pipelines/{name}/pipeline.py`

**What it looks like** (from `pipelines/example_churn/pipeline.py`):

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(query="SELECT ... FROM `{bq_dataset}.raw_events`", output_table="raw"))
    .transform(BQTransform(sql="SELECT ... FROM `{bq_dataset}.raw`", output_table="features"))
    .train(TrainModel(trainer_image="...", machine_type="n1-standard-8"))
    .evaluate(EvaluateModel(metrics=["auc"], gate={"auc": 0.78}))
    .deploy(DeployModel(endpoint_name="churn-classifier"))
    .build()
)
```

**Available components:**

| Stage | Component | What it does |
|---|---|---|
| `.ingest()` | `BigQueryExtract` | Run BQ query, export to GCS as Parquet |
| `.ingest()` | `GCSExtract` | Copy files from GCS source to staging prefix |
| `.transform()` | `BQTransform` | Run SQL transform, materialize to BQ table |
| `.write_features()` | `WriteFeatures` | Sync BQ → Feature Store online store |
| `.read_features()` | `ReadFeatures` | Read features from Feature Store |
| `.train()` | `TrainModel` | Submit Vertex AI Custom Training Job |
| `.evaluate()` | `EvaluateModel` | Compute metrics + gate (halt if threshold not met) |
| `.deploy()` | `DeployModel` | Upload model to registry, deploy to endpoint |

Template variables like `{bq_dataset}`, `{run_date}`, `{gcs_prefix}`, `{artifact_registry}` are auto-resolved from your git branch context.

### 2. DAGBuilder — Composer DAGs (Airflow)

For orchestration workflows that run on Cloud Composer. Can include BQ queries, Vertex pipelines, notifications, sensors — anything Airflow supports.

```
dag.py → DAGBuilder → DAGDefinition
    → DAGCompiler → standalone Airflow DAG Python file → Composer GCS bucket
```

**File:** `pipelines/{name}/dag.py`

**What it looks like** (from `pipelines/daily_sales_etl/dag.py`):

```python
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(name="daily_sales_etl", schedule="30 7 * * *", tags=["etl", "sales"])
    .task(
        BQQueryTask(
            sql="SELECT * FROM `{bq_dataset}.raw_orders` WHERE order_date = '{run_date}'",
            destination_table="staged_orders",
        ),
        name="extract_raw_orders",
    )
    .task(
        BQQueryTask(sql="SELECT ... FROM `{bq_dataset}.staged_orders` GROUP BY ...", destination_table="summary"),
        name="transform_summary",
    )
    .task(
        EmailTask(to=["team@company.com"], subject="[{namespace}] ETL Complete"),
        name="notify_team",
    )
    .build()
)
```

**Available task types:**

| Task | Airflow Operator | Purpose |
|---|---|---|
| `BQQueryTask` | `BigQueryInsertJobOperator` | Run SQL queries |
| `VertexPipelineTask` | `VertexPipelineOperator` (custom) | Submit a Vertex AI Pipeline |
| `EmailTask` | `EmailOperator` | Send email notifications |

**Key difference from PipelineBuilder:**
- DAGBuilder supports explicit `depends_on` for parallel tasks and fan-in patterns
- DAGBuilder compiles to a static Python file (no framework dependency at Airflow parse time)
- PipelineBuilder steps are always sequential; DAGBuilder tasks can be parallel

---

## Every CLI Command

### `gml context show` — See your resolved namespace

Shows what GCP resources the framework will target based on your current git branch.

```bash
uv run gml context show
```

Output:
```
GCP ML Framework — context for branch 'feature_dagFactory'

               Identity
  team             dsci
  project          examplechurn
  branch (raw)     feature_dagFactory
  branch (slug)    feature-dagfactory
  git_state        DEV

                GCP
  project         gcp-gap-demo-dev
  region          us-central1

                                 Resource Names
  namespace                    dsci-examplechurn-feature-dagfactory
  gcs_bucket                   dsci-examplechurn
  gcs_prefix                   gs://dsci-examplechurn/feature-dagfactory/
  bq_dataset                   dsci_examplechurn_feature_dagf
  feature_store_id             dsci_examplechurn
  dag_id pattern               dsci_examplechurn_feature_dagf__pipeline
  secret_prefix                dsci-examplechurn-feature-dagfactory
```

Override the branch: `uv run gml context show --branch main` (shows STAGING context).

JSON output: `uv run gml context show --json`

### `gml run` — Execute a pipeline

**Local run (default — no GCP needed):**

```bash
# Full local execution with DuckDB stubs and seed data
uv run gml run example_churn --local

# Print the execution plan without running anything
uv run gml run example_churn --local --dry-run

# Override the run date
uv run gml run example_churn --local --run-date 2026-01-15
```

Output of `--dry-run`:
```
Pipeline: 'churn_prediction'  (schedule='0 6 * * 1')
Step                           Stage                Component
----------------------------------------------------------------------
  ingest_raw_events            ingest               BigQueryExtract
  engineer_features            transform            BQTransform
  write_user_features          write_features       WriteFeatures
  train_churn_model            train                TrainModel
  evaluate_model               evaluate             EvaluateModel
  deploy_churn_model           deploy               DeployModel
```

**How local run works:**
1. Seeds DuckDB from CSV/Parquet files in `pipelines/{name}/seeds/`
2. Calls each component's `local_run()` method sequentially
3. BigQueryExtract/BQTransform use DuckDB with BQ→DuckDB SQL translation
4. TrainModel writes a placeholder model JSON
5. EvaluateModel returns synthetic metrics
6. DeployModel prints a stub endpoint name

**Vertex AI run (requires GCP credentials):**

```bash
# Submit to Vertex AI (async — returns immediately)
uv run gml run example_churn --vertex

# Submit and wait for completion
uv run gml run example_churn --vertex --sync

# Run all pipelines
uv run gml run --vertex --all

# Disable KFP step caching
uv run gml run example_churn --vertex --no-cache
```

**Compile only (for CI validation):**

```bash
# Compile all pipelines to KFP YAML
uv run gml run --compile-only --all

# Compile one pipeline to a specific directory
uv run gml run example_churn --compile-only --out /tmp/compiled
```

Produces `compiled_pipelines/churn_prediction.yaml` (KFP v2 YAML).

### `gml deploy dags` — Generate and sync Airflow DAGs

```bash
# Generate DAG files (dry run — no GCS upload)
uv run gml deploy dags --dry-run

# Generate and upload to Composer GCS bucket
uv run gml deploy dags
```

Output of `--dry-run`:
```
Generated (dag.py): dags/dsci_examplechurn_feature_dagf__daily_sales_etl.py
(dry-run) would sync to: gs://...-composer/dags/...
Generated (pipeline.py): dags/dsci_examplechurn_feature_dagf__churn_prediction.py
(dry-run) would sync to: gs://...-composer/dags/...
```

**How it works:**
1. Scans `pipelines/` for `dag.py` (DAGBuilder) or `pipeline.py` (PipelineBuilder)
2. If `dag.py` exists → compiles via DAGCompiler to a standalone Airflow DAG file
3. If only `pipeline.py` exists → auto-wraps in a VertexPipelineTask DAG
4. Writes generated DAG files to `dags/` directory
5. If Composer is configured → uploads to Composer GCS bucket

### `gml deploy features` — Upsert Feature Store schemas

```bash
# Deploy all entity schemas (dry run)
uv run gml deploy features --dry-run

# Deploy specific entities
uv run gml deploy features user item

# Deploy all entities for real
uv run gml deploy features
```

Reads YAML from `feature_schemas/*.yaml` and calls the Feature Store API to create/update entity types and features.

### `gml init` — Scaffold a new project or pipeline

```bash
# Scaffold a brand new project
uv run gml init project dsci churn-pred \
  --dev-project my-gcp-dev \
  --staging-project my-gcp-staging \
  --prod-project my-gcp-prod

# Add a new pipeline to an existing project
uv run gml init pipeline my_new_pipeline
```

`init project` creates: `framework.yaml`, `feature_schemas/`, `pipelines/`, `.github/workflows/`, `tests/`, `.python-version`, `.gitignore`.

`init pipeline` creates: `pipelines/{name}/pipeline.py` (with template), `config.yaml`, `sql/{name}_features.sql`.

### `gml promote` — Promote STAGE → PROD

```bash
# Promote validated STAGE artifacts to PROD via release tag
uv run gml promote --from main --to prod --tag v1.2.3

# Dry run
uv run gml promote --from main --to prod --tag v1.2.3 --dry-run
```

Copies compiled pipeline YAML from STAGE GCS to PROD GCS. Generates PROD DAG files. No recompilation — only validated artifacts are promoted.

### `gml teardown` — Delete ephemeral DEV resources

```bash
# Preview what would be deleted
uv run gml teardown --branch feature/my-experiment --dry-run

# Delete (with confirmation prompt)
uv run gml teardown --branch feature/my-experiment

# Skip confirmation
uv run gml teardown --branch feature/my-experiment --confirm
```

Safety check: refuses to teardown STAGING or PROD. Only DEV branches.

Currently deletes: GCS prefix, BQ dataset. (Vertex experiments, endpoints, Feature Store views not yet cleaned up — noted in next_steps.md.)

---

## Running Tests

```bash
# Run all 167 unit tests
uv run pytest tests/unit/

# Run with verbose output
uv run pytest tests/unit/ -v

# Run a specific test file
uv run pytest tests/unit/test_dag_builder.py

# Run a specific test
uv run pytest tests/unit/test_naming.py::TestNamingConvention::test_namespace

# Run with coverage
uv run pytest tests/unit/ --cov=gcp_ml_framework
```

**Test breakdown:**

| Test File | Tests | What It Covers |
|---|---|---|
| `test_naming.py` | 23 | Namespace resolution, slugification, BQ naming, feature views |
| `test_pipeline_builder.py` | 28 | PipelineBuilder DSL, step sequencing, compiler integration |
| `test_dag_builder.py` | 23 | DAGBuilder DSL, depends_on, topological sort, cycle detection |
| `test_dag_compiler.py` | 15 | DAG file rendering, template resolution, Airflow macro conversion |
| `test_dag_tasks.py` | 29 | BQQueryTask, EmailTask, VertexPipelineTask, TaskConfig |
| `test_config.py` | 13 | Git state resolution, environment mapping, config layering |
| `test_context.py` | 9 | MLContext creation, property delegation, production checks |
| `test_feature_schema.py` | 10 | YAML schema parsing, feature groups, entity schemas |
| `test_secrets.py` | 7 | Secret resolution, env var fallback, `!secret` dict resolution |
| `test_sql_compat.py` | 10 | BigQuery → DuckDB SQL translation (7 functions) |

```bash
# Linting
uv run ruff check .

# Type checking
uv run mypy .
```

---

## How Branch Isolation Works

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
BigQuery:    dsci_examplechurn_feature_user_embeddings
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
framework defaults → framework.yaml → pipelines/{name}/config.yaml → env vars → CLI flags
```

**`framework.yaml`** (project root):
```yaml
team: dsci
project: examplechurn
gcp:
  dev_project_id: gcp-gap-demo-dev
  staging_project_id: gcp-gap-demo-staging
  prod_project_id: gcp-gap-demo-prod
  region: us-central1
  artifact_registry_host: us-central1-docker.pkg.dev
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

## The Example Pipelines

### 1. `pipelines/example_churn/` — Full ML Loop

**What it does:** Weekly churn model training and deployment.

```
ingest_raw_events (BigQueryExtract)
    → engineer_features (BQTransform — SAFE_DIVIDE, LN, CURRENT_TIMESTAMP)
        → write_user_features (WriteFeatures — 6 behavioral features)
            → train_churn_model (TrainModel — sklearn LogisticRegression)
                → evaluate_model (EvaluateModel — AUC gate ≥ 0.78)
                    → deploy_churn_model (DeployModel — sklearn serving container)
```

**Seed data:** `seeds/raw_user_events.csv` — 10 users with session counts, purchase data, and churn labels.

**Trainer:** `trainer/train.py` — sklearn pipeline (StandardScaler + LogisticRegression), reads from BQ, saves model.pkl to GCS.

**Try it:**
```bash
uv run gml run example_churn --local --dry-run    # see the plan
uv run gml run example_churn --local               # run with DuckDB
```

### 2. `pipelines/daily_sales_etl/` — Pure ETL DAG

**What it does:** Daily extract → transform → email notification. No ML, no Vertex AI.

```
extract_raw_orders (BQQueryTask)
    → transform_daily_summary (BQQueryTask — GROUP BY category, region)
        → notify_team (EmailTask)
```

**Seed data:** `seeds/raw_orders.csv` — 8 orders with categories, amounts, regions.

**Try it:**
```bash
uv run gml deploy dags --dry-run    # see generated DAG file
```

---

## Project File Structure

```
Sandbox/
├── framework.yaml                  # Team/project/GCP config
├── pyproject.toml                  # Dependencies + tool config
├── uv.lock                        # Pinned dependency lockfile
│
├── gcp_ml_framework/              # The framework library (50 files, 4,400 lines)
│   ├── naming.py                  # All GCP resource names from {team}-{project}-{branch}
│   ├── config.py                  # Pydantic v2 layered config
│   ├── context.py                 # MLContext — single runtime object
│   │
│   ├── pipeline/                  # ML Pipeline engine
│   │   ├── builder.py             #   PipelineBuilder fluent DSL
│   │   ├── compiler.py            #   → KFP v2 YAML
│   │   └── runner.py              #   LocalRunner (DuckDB) + VertexRunner
│   │
│   ├── dag/                       # Composer DAG engine
│   │   ├── builder.py             #   DAGBuilder fluent DSL
│   │   ├── compiler.py            #   → Airflow DAG Python file
│   │   ├── factory.py             #   Backward-compat + discovery
│   │   ├── operators.py           #   VertexPipelineOperator
│   │   └── tasks/                 #   BQQueryTask, EmailTask, VertexPipelineTask
│   │
│   ├── components/                # KFP v2 component library
│   │   ├── base.py                #   BaseComponent ABC
│   │   ├── ingestion/             #   BigQueryExtract, GCSExtract
│   │   ├── transformation/        #   BQTransform, PandasTransform
│   │   ├── feature_store/         #   WriteFeatures, ReadFeatures
│   │   └── ml/                    #   TrainModel, EvaluateModel, DeployModel
│   │
│   ├── feature_store/             # Feature Store schema + client
│   │   ├── schema.py              #   YAML → typed dataclasses
│   │   └── client.py              #   Feature Store API client
│   │
│   ├── secrets/                   # Secret Manager client
│   │   └── client.py              #   !secret resolution + local env fallback
│   │
│   ├── cli/                       # gml CLI (Typer)
│   │   ├── main.py                #   Entrypoint + command registration
│   │   ├── cmd_init.py            #   gml init project/pipeline
│   │   ├── cmd_run.py             #   gml run (local/vertex/compile-only)
│   │   ├── cmd_deploy.py          #   gml deploy dags/features
│   │   ├── cmd_context.py         #   gml context show
│   │   ├── cmd_promote.py         #   gml promote
│   │   ├── cmd_teardown.py        #   gml teardown
│   │   └── _helpers.py            #   Shared CLI utilities
│   │
│   └── utils/                     # Helpers
│       ├── gcs.py                 #   GCS upload/delete/copy
│       ├── bq.py                  #   BQ dataset delete/table check
│       ├── sql_compat.py          #   BQ → DuckDB SQL translation
│       └── logging.py             #   JSON logging setup
│
├── pipelines/                     # User-defined pipelines
│   ├── example_churn/             #   ML pipeline (6 steps, seed data, trainer)
│   └── daily_sales_etl/           #   ETL DAG (3 tasks, seed data)
│
├── feature_schemas/               # Entity feature definitions
│   ├── user.yaml                  #   9 features (behavioral + demographic)
│   └── item.yaml                  #   5 features (catalog + engagement)
│
├── tests/unit/                    # 167 unit tests
│
└── docs/                          # Documentation
    ├── architecture/plan.md       #   System design + naming conventions
    ├── planning/next_steps.md     #   Full codebase audit + priorities
    ├── planning/current_state.md  #   What works / what doesn't
    ├── planning/feature_plan.md   #   DAGBuilder design doc
    ├── prerequisite/infrastructure.md  # GCP provisioning steps
    ├── guides/integration.md      #   Bring existing ML code into framework
    └── reference/deep_research_report.md  # GCP platform research
```

---

## Quick Reference: Common Workflows

```bash
# "I want to see what resources my branch would use"
uv run gml context show

# "I want to iterate on SQL locally"
uv run gml run my_pipeline --local

# "I want to validate my pipeline compiles"
uv run gml run my_pipeline --compile-only

# "I want to test on real GCP"
uv run gml run my_pipeline --vertex --sync

# "I want to generate Airflow DAGs"
uv run gml deploy dags --dry-run

# "I want to run all tests"
uv run pytest tests/unit/

# "I want to lint"
uv run ruff check .

# "I want to add a new pipeline"
uv run gml init pipeline my_new_pipeline
# Then edit pipelines/my_new_pipeline/pipeline.py
```
