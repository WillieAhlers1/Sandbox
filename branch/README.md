# GCP ML Framework
#

Python library + CLI (`gml`) for branch-isolated ML pipelines on Google Cloud Platform. One Python file per pipeline. One command to run, deploy, or promote.

## How It Works

Every branch gets its own GCP namespace derived from `{team}-{project}-{branch}`:

```
branch: feature/user-embeddings
  GCS:       gs://dsci-churn-pred/feature-user-embeddings/
  BigQuery:  dsci_churn_pred_feature_user_embeddings
  Vertex AI: dsci-churn-pred-feature-user-embeddings-{pipeline}
```

Git state determines environment — no `if env == "prod"` anywhere:

| Git State | Environment | Lifecycle |
|---|---|---|
| `feature/*`, `hotfix/*` | DEV | Ephemeral — auto-cleanup on merge |
| `main` | STAGING | Persistent |
| Release tag `v*` | PROD | Immutable — promoted from STAGING only |

## Quickstart

```bash
pip install uv && uv sync

gml init project dsci churn-pred \
  --dev-project my-gcp-dev \
  --staging-project my-gcp-staging \
  --prod-project my-gcp-prod

gml init pipeline churn_prediction
# Edit pipelines/churn_prediction/pipeline.py

gml run churn_prediction --local    # DuckDB stubs, no GCP needed
gml run churn_prediction --vertex   # Submit to Vertex AI
gml deploy dags                     # Sync DAGs to Composer
```

## Pipeline DSL

```python
pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(query="SELECT * FROM `{bq_dataset}.raw_events`", output_table="raw"))
    .transform(BQTransform(sql_file="sql/features.sql", output_table="features"))
    .train(TrainModel(trainer_image="...", machine_type="n1-standard-8"))
    .evaluate(EvaluateModel(metrics=["auc"], gate={"auc": 0.78}))
    .deploy(DeployModel(endpoint_name="churn-classifier"))
    .build()
)
```

That's the entire pipeline definition. No DAG code. No KFP YAML. No operator wiring.

## DAGBuilder DSL — Composer Orchestration

For workflows that go beyond a single Vertex pipeline — ETL jobs, notifications, sensors, multi-pipeline orchestration — use the `DAGBuilder` DSL. It compiles to Airflow DAG files and deploys to Cloud Composer.

```python
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks import BQQueryTask, VertexPipelineTask, EmailTask

dag = (
    DAGBuilder(name="daily_sales_etl", schedule="0 6 * * *")
    .task(BQQueryTask(
        name="extract_sales",
        sql="SELECT * FROM `{bq_dataset}.raw_sales` WHERE dt = '{{ ds }}'",
    ))
    .task(BQQueryTask(
        name="transform_features",
        sql_file="sql/sales_features.sql",
        depends_on=["extract_sales"],
    ))
    .task(VertexPipelineTask(
        name="train_model",
        pipeline="sales_forecast",
        depends_on=["transform_features"],
    ))
    .task(EmailTask(
        name="notify_team",
        to=["team@example.com"],
        subject="Pipeline complete",
        depends_on=["train_model"],
    ))
    .build()
)
```

Two-level orchestration: Composer handles scheduling, dependencies, and non-ML tasks. Vertex AI handles ML step execution, caching, and GPU scheduling.

## CLI Reference

```
gml init project <team> <project>      Scaffold a new project
gml init pipeline <name>               Add a pipeline
gml context show                       Show resolved namespace and resources
gml run <pipeline> --local             Run locally (default)
gml run <pipeline> --vertex            Submit to Vertex AI
gml run --compile-only [--all]         Compile to KFP YAML only
gml deploy dags                        Sync DAGs to Composer
gml deploy features [entity ...]       Upsert Feature Store schemas
gml promote --from main --to prod      Promote STAGE → PROD
gml teardown --branch <branch>         Delete DEV resources
```

## Documentation

| Document | Description |
|---|---|
| [Architecture Plan](docs/architecture/plan.md) | System design, naming conventions, implementation phases |
| [Infrastructure Setup](docs/prerequisite/infrastructure.md) | GCP project provisioning steps |
| [Integration Guide](docs/guides/integration.md) | Bring existing ML code into the framework |
| [Current State](docs/planning/current_state.md) | What works, what doesn't, known issues |
| [Next Steps](docs/planning/next_steps.md) | Prioritized roadmap |
| [DAG Factory Feature Plan](docs/planning/feature_plan.md) | DAGBuilder DSL design |
| [Deep Research Report](docs/reference/deep_research_report.md) | GCP platform research and analysis |

## Project Layout

```
framework.yaml                  Team/project config
pipelines/                      One directory per pipeline (pipeline.py + config.yaml)
feature_schemas/                Entity feature definitions (YAML)
gcp_ml_framework/               Framework source
  naming.py, config.py, context.py, secrets/
  components/                   BaseComponent + 7 built-ins
  pipeline/                     PipelineBuilder, compiler, runner
  dag/                          DAG factory + operators
  feature_store/                Schema parser + client
  cli/                          gml CLI commands
tests/unit/                     99 unit tests
```
