# GCP ML Framework

Python library + CLI (`gml`) for branch-isolated ML pipelines and data workflows on Google Cloud Platform.

One Python file per pipeline. One command to run, deploy, or promote. Every GCP resource is automatically scoped to `{team}-{project}-{branch}` — no hardcoded project IDs, no `if env == "prod"`, no resource collisions between branches.

## How It Works

Your git branch determines your entire GCP namespace:

```
branch: feature/user-embeddings
  GCS bucket:    gs://dsci-churn-pred/feature-user-embeddings/
  BigQuery:      dsci_churn_pred_feature_user_embeddings
  Vertex AI:     dsci-churn-pred-feature-user-embeddings-{pipeline}
  Composer DAG:  dsci_churn_pred_feature_user_embe__{pipeline}
  Feature View:  user_behavioral_feature_user_embeddings
```

| Git State | Environment | GCP Project | Lifecycle |
|---|---|---|---|
| `feature/*`, `hotfix/*`, other | DEV | `dev_project_id` | Ephemeral — auto-cleanup on merge |
| `main` | STAGING | `staging_project_id` | Persistent — full integration |
| Release tag `v*` | PROD | `prod_project_id` | Immutable — promoted from STAGING only |

## Quickstart

```bash
# Install dependencies
pip install uv && uv sync

# Scaffold a new project
gml init project dsci churn-pred \
  --dev-project my-gcp-dev \
  --staging-project my-gcp-staging \
  --prod-project my-gcp-prod

# Add a pipeline
gml init pipeline churn_prediction
# Edit pipelines/churn_prediction/pipeline.py

# Run locally (DuckDB stubs — no GCP needed)
gml run churn_prediction --local

# Submit to Vertex AI
gml run churn_prediction --vertex

# Compile and deploy DAGs to Composer
gml compile --all
gml deploy --all
```

## Two DSLs, Two Levels of Orchestration

The framework provides two complementary DSLs:

### PipelineBuilder — ML Pipelines (Vertex AI)

For ML workflows that compile to KFP v2 YAML and run on Vertex AI Pipelines. Steps execute sequentially with automatic data wiring.

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(
        query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
        output_table="raw",
    ))
    .transform(BQTransform(sql_file="sql/features.sql", output_table="features"))
    .train(TrainModel(machine_type="n2-standard-8", hyperparameters={"lr": 0.05}))
    .evaluate(EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.78}))
    .deploy(DeployModel(endpoint_name="churn-classifier"))
    .build()
)
```

### DAGBuilder — Composer DAGs (Airflow)

For orchestration workflows with parallel tasks, fan-out/fan-in patterns, notifications, and multi-pipeline coordination. Compiles to standalone Airflow DAG files with zero framework imports at parse time.

```python
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(name="sales_analytics", schedule="0 8 * * *")
    .task(BQQueryTask(sql_file="sql/extract.sql", destination_table="staged"), name="extract", depends_on=[])
    .task(BQQueryTask(sql_file="sql/aggregate.sql", destination_table="agg"), name="aggregate", depends_on=["extract"])
    .task(VertexPipelineTask(pipeline_name="sales_forecast"), name="forecast", depends_on=["aggregate"])
    .task(EmailTask(to=["team@co.com"], subject="Done"), name="notify", depends_on=["forecast"])
    .build()
)
```

## Component Library

| Stage | Component | What It Does |
|---|---|---|
| Ingestion | `BigQueryExtract` | Run BQ SQL query, export results to GCS as Parquet |
| Ingestion | `GCSExtract` | Copy files from a GCS source path to branch staging prefix |
| Transformation | `BQTransform` | Run SQL transformation, materialize to BQ table |
| Feature Store | `WriteFeatures` | Register BQ table as Vertex AI Feature Store v2 FeatureGroup (metadata only) |
| Feature Store | `ReadFeatures` | Read features from Feature Store (offline from BQ, online from Bigtable) |
| ML | `TrainModel` | Submit Vertex AI Custom Training Job with versioned model output |
| ML | `EvaluateModel` | Compute metrics + quality gates (halt pipeline if threshold not met) |
| ML | `DeployModel` | Upload model to Vertex AI Model Registry, deploy to Endpoint with canary support |

Every component implements `as_kfp_component()` (for Vertex AI) and `local_run()` (for local execution with DuckDB).

## DAG Task Library

| Task | Airflow Operator | Purpose |
|---|---|---|
| `BQQueryTask` | `BigQueryInsertJobOperator` | Run SQL with template variables, optional `sql_file` |
| `VertexPipelineTask` | Custom operator | Submit a compiled Vertex AI Pipeline |
| `EmailTask` | `EmailOperator` | Send notifications with template variables |

## CLI Reference

```
gml init project <team> <project>      Scaffold a new project with framework.yaml, CI/CD, schemas
gml init pipeline <name>               Add a pipeline directory with template files
gml context show [--branch] [--json]   Show resolved namespace, GCP project, resource names
gml run <pipeline> [--local|--vertex|--composer]  Run locally, submit to Vertex AI, or trigger on Composer
gml compile <pipeline> [--all]         Compile to KFP YAML + Airflow DAG files
gml deploy <pipeline> [--all]          Compile + upload DAGs, YAMLs, feature schemas
gml teardown --branch <branch>         Delete ephemeral DEV resources (GCS, BQ)
```

## Example Pipelines

The repo ships with 3 working pipelines demonstrating different patterns:

| Pipeline | Type | Pattern | Description |
|---|---|---|---|
| `churn_prediction` | PipelineBuilder | Pure ML | Ingest → Transform → Features → Train → Evaluate (gate) → Deploy |
| `sales_analytics` | DAGBuilder | Fan-out/fan-in | 3 parallel extractions → 3 aggregations → report → notify (8 tasks) |
| `recommendation_engine` | DAGBuilder | Hybrid ML | BQ extraction → 2 inline Vertex pipelines (features + training) → notify |

All include seed data for local testing with `gml run <name> --local`.

## Infrastructure

Infrastructure is managed via Terraform modules in `terraform/`:

| Module | Resource | Purpose |
|---|---|---|
| `composer` | `google_composer_environment` | Cloud Composer 3 with workloads_config |
| `artifact_registry` | `google_artifact_registry_repository` | Docker repos for containers |
| `iam` | Service accounts + WIF | Composer SA, Pipeline SA, GitHub Actions OIDC |
| `storage` | `google_storage_bucket` | GCS buckets with versioning |

Per-environment configs in `terraform/envs/{dev,staging,prod}/` with scaled workloads (dev=small, staging=moderate, prod=production-grade).

```bash
cd terraform/envs/dev
terraform init && terraform plan -var-file=terraform.tfvars
```

## Testing

```bash
uv run pytest tests/ -v              # 371 tests, all passing
uv run pytest tests/unit/            # Unit tests only
uv run pytest tests/integration/     # E2E integration tests
uv run ruff check .                  # Lint
```

| Test Suite | Tests | Coverage |
|---|---|---|
| Unit — Components | 45 | All 8 components: defaults, local_run(), as_kfp_component() |
| Unit — CLI | 22 | All 6 CLI commands with typer CliRunner |
| Unit — Config/Context/Naming | 45 | Config layering, git state, namespace resolution |
| Unit — DAG Builder/Compiler/Tasks | 67 | DSL, topological sort, compilation, task types |
| Unit — Pipeline Builder/Compiler | 28 | PipelineBuilder DSL, KFP compilation |
| Unit — Feature Store/Secrets/SQL | 27 | Schema parsing, v2 API, secrets, BQ→DuckDB compat |
| Unit — Phase regression | 112 | Phase 1-3 specific regression tests |
| Integration — E2E | 24 | Full compile + local run for all 4 pipelines |

## Config System

Resolution order (later wins):

```
framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags
```

Environment variables use `GML_` prefix with `__` for nesting:

```bash
GML_TEAM=dsci
GML_GCP__REGION=europe-west1
GML_ENV_OVERRIDE=staging
```

Secrets use `!secret key` references, resolved from GCP Secret Manager in cloud or environment variables locally.

## Project Layout

```
.
├── framework.yaml                      # Team/project/GCP config (single source of truth)
├── pyproject.toml                      # Dependencies + tool config
│
├── gcp_ml_framework/                   # Framework library (51 files, ~4,700 lines)
│   ├── naming.py                       #   GCP resource names from {team}-{project}-{branch}
│   ├── config.py                       #   Pydantic v2 layered config + git state resolution
│   ├── context.py                      #   MLContext — immutable runtime object
│   │
│   ├── pipeline/                       #   ML Pipeline engine
│   │   ├── builder.py                  #     PipelineBuilder fluent DSL → PipelineDefinition
│   │   ├── compiler.py                 #     → KFP v2 YAML (Vertex AI)
│   │   └── runner.py                   #     LocalRunner (DuckDB) + VertexRunner (GCP)
│   │
│   ├── dag/                            #   Composer DAG engine
│   │   ├── builder.py                  #     DAGBuilder fluent DSL → DAGDefinition
│   │   ├── compiler.py                 #     → Standalone Airflow DAG Python file
│   │   ├── runner.py                   #     DAGLocalRunner (DuckDB, topological execution)
│   │   ├── factory.py                  #     Auto-wrapping + discovery
│   │   ├── operators.py                #     VertexPipelineOperator for Airflow
│   │   └── tasks/                      #     BQQueryTask, EmailTask, VertexPipelineTask
│   │
│   ├── components/                     #   KFP v2 component library (8 components)
│   │   ├── base.py                     #     BaseComponent ABC + ComponentConfig
│   │   ├── ingestion/                  #     BigQueryExtract, GCSExtract
│   │   ├── transformation/             #     BQTransform
│   │   ├── feature_store/              #     WriteFeatures, ReadFeatures
│   │   └── ml/                         #     TrainModel, EvaluateModel, DeployModel
│   │
│   ├── feature_store/                  #   Vertex AI Feature Store v2
│   │   ├── schema.py                   #     YAML → typed EntitySchema/FeatureGroupSchema
│   │   └── client.py                   #     FeatureGroup, FeatureView, FeatureOnlineStore
│   │
│   ├── secrets/client.py               #   Secret Manager + local env var fallback
│   ├── cli/                            #   gml CLI (Typer + Rich)
│   └── utils/                          #   GCS, BQ, SQL compat, logging helpers
│
├── pipelines/                          #   User-defined pipelines
│   ├── churn_prediction/               #     Pure ML pipeline (pipeline.py + seeds + trainer)
│   ├── sales_analytics/                #     Fan-out/fan-in DAG (dag.py + 7 SQL files + seeds)
│   └── recommendation_engine/          #     Hybrid DAG (dag.py + 2 inline Vertex pipelines + trainer + seeds)
│
├── feature_schemas/                    #   Entity feature definitions (YAML)
│   ├── user.yaml                       #     9 features (behavioral + demographic)
│   └── item.yaml                       #     5 features (catalog + engagement)
│
├── terraform/                          #   Infrastructure as Code
│   ├── modules/                        #     Reusable modules (composer, AR, IAM, storage)
│   └── envs/{dev,staging,prod}/        #     Per-environment configs + tfvars
│
├── docker/base/                        #   Base Docker images (python, ML)
├── scripts/                            #   bootstrap.sh, docker_build.sh
├── tests/                              #   371 tests (16 unit + 1 integration file)
│
└── docs/                               #   Documentation
    ├── architecture/plan.md            #     System design + naming conventions
    ├── guides/integration.md           #     Bring existing ML code into framework
    ├── prerequisite/infrastructure.md  #     GCP provisioning (manual + Terraform)
    └── planning/                       #     Roadmap + guidelines
```

## Documentation

| Document | Description |
|---|---|
| [Architecture Plan](docs/architecture/plan.md) | System design, naming conventions, layer diagram, key decisions |
| [Integration Guide](docs/guides/integration.md) | Step-by-step: bring existing ML code into the framework |
| [Infrastructure Setup](docs/prerequisite/infrastructure.md) | GCP provisioning (manual CLI + Terraform modules) |
| [Framework Walkthrough](docs/understanding.md) | Exhaustive guide: every DSL, component, CLI command, and workflow |
| [Project Guidelines](docs/planning/project_guideline.md) | Development standards and conventions |
| [Next Steps](docs/planning/next_steps.md) | Roadmap and implementation phases |

## Key Design Decisions

| Decision | Rationale |
|---|---|
| KFP v2 + Airflow | KFP for ML (artifacts, lineage, GPUs). Airflow for scheduling and cross-pipeline deps. |
| Branch = namespace | Isolation is structural. No human discipline required. |
| DuckDB for local | SQL-compatible with BigQuery, zero infrastructure, in-process. |
| Feature Store v2 (BQ-native) | No data movement for offline. Bigtable for online serving. |
| Compiled DAGs (no framework imports) | Airflow parses DAGs every 30s. Zero import overhead at parse time. |
| N2/C3 machine types | Modern Compute Engine families. No legacy N1. |
| Terraform for infra | Composer 3, AR, GCS, IAM managed as code. Framework manages ephemeral resources. |
| `gml` CLI over Makefiles | Type-safe, self-documenting, testable with typer CliRunner. |
