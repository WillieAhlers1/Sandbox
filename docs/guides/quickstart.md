# Quickstart — Your First Pipeline in 15 Minutes

Get from zero to a running pipeline locally. No GCP account needed.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| uv | latest | `pip install uv` |
| Git | 2.x+ | Already installed on most systems |
| Docker | 24+ | Only needed for GCP deployment (not local runs) |
| gcloud | latest | Only needed for GCP deployment |

## Install

```bash
git clone <your-repo-url> && cd <repo-name>
uv sync
```

Verify the CLI works:

```bash
uv run gml context show --branch feature/test
```

You should see a table of resolved GCP resource names.

---

## Option A: Create an ML Pipeline (Vertex AI)

Use this when your workflow is a linear ML pipeline: ingest → transform → train → evaluate → deploy.

```bash
gml init pipeline my_model
```

This creates:

```
pipelines/my_model/
├── pipeline.py          # PipelineBuilder definition
├── config.yaml          # Pipeline-level config overrides
└── sql/
    └── my_model_features.sql   # Feature SQL template
```

### What to edit

**`pipeline.py`** — The pipeline definition. Each step uses a framework component:

```python
pipeline = (
    PipelineBuilder(name="my_model", schedule="@daily")
    .ingest(BigQueryExtract(query="SELECT ...", output_table="raw"))
    .transform(BQTransform(sql_file="sql/my_model_features.sql", output_table="features"))
    .train(TrainModel(machine_type="n2-standard-4"))
    .evaluate(EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.75}))
    .deploy(DeployModel(endpoint_name="my-model-endpoint"))
    .build()
)
```

Available components: `BigQueryExtract`, `GCSExtract`, `BQTransform`, `WriteFeatures`, `ReadFeatures`, `TrainModel`, `EvaluateModel`, `DeployModel`.

**`sql/my_model_features.sql`** — BigQuery SQL with `{bq_dataset}` and `{run_date}` template variables (auto-resolved by framework).

> **Note**: ML pipelines are automatically wrapped in a Composer DAG at compile time. You never write Airflow code — the framework handles it.

---

## Option B: Create a Data Pipeline (Composer DAG)

Use this when you need custom Airflow orchestration: parallel tasks, fan-out/fan-in, notifications, or multi-pipeline coordination.

```bash
gml init pipeline my_report --dag
```

This creates:

```
pipelines/my_report/
├── dag.py               # DAGBuilder definition
├── config.yaml          # Schedule + tags
└── sql/
    ├── extract.sql      # Extraction query template
    └── transform.sql    # Transformation query template
```

### What to edit

**`dag.py`** — The DAG definition. Each task maps to an Airflow operator:

```python
dag = (
    DAGBuilder(name="my_report", schedule="@daily")
    .task(BQQueryTask(sql_file="sql/extract.sql", destination_table="staged"), name="extract", depends_on=[])
    .task(BQQueryTask(sql_file="sql/transform.sql", destination_table="output"), name="transform", depends_on=["extract"])
    .task(EmailTask(to=["team@co.com"], subject="Done"), name="notify", depends_on=["transform"])
    .build()
)
```

Available task types: `BQQueryTask` (BigQuery SQL), `EmailTask` (notifications), `VertexPipelineTask` (submit a Vertex AI pipeline from within a DAG).

**`sql/*.sql`** — BigQuery SQL with `{bq_dataset}` and `{run_date}` template variables.

Use `depends_on` to control execution order. Tasks with no dependencies run in parallel.

---

## Add Seed Data (Optional)

For local testing, place CSV files in `pipelines/<name>/seeds/`:

```
pipelines/my_model/
└── seeds/
    └── raw_events.csv    # Column headers + sample rows
```

The local runner loads these into DuckDB automatically. Table names match filenames (without `.csv`).

> **Convention**: Name seed CSVs to match the BQ tables your SQL queries reference.

---

## Run Locally

No GCP account needed. The framework uses DuckDB as a local BigQuery substitute.

```bash
# Run an ML pipeline
gml run my_model --local

# Run a DAG
gml run my_report --local

# Preview execution plan without running
gml run my_model --local --dry-run
```

What happens locally:
- BigQuery SQL → translated to DuckDB (backticks, `DATE_SUB`, `SAFE_DIVIDE`, etc. auto-converted)
- Seed CSVs → loaded into DuckDB tables
- `TrainModel` → trains a real sklearn model on local data
- `EvaluateModel` → computes real metrics (auc, f1, etc.)
- `EmailTask` → prints to console instead of sending email

---

## Deploy to GCP

Once your pipeline works locally, deploy to GCP:

```bash
# 1. Compile to KFP YAML + Airflow DAG files
gml compile my_model

# 2. Upload DAGs and pipeline YAMLs to GCS/Composer
gml deploy my_model

# 3. Trigger via Composer
gml run my_model --composer --run-date 2024-01-15
```

For full GCP setup (Terraform, Docker builds, seed data loading), see the [Demo Walkthrough](../demo.md).

---

## Pipeline vs DAG — Which to Choose?

| | ML Pipeline (`pipeline.py`) | Data Pipeline (`dag.py`) |
|---|---|---|
| **Use when** | Linear ML workflow | Custom orchestration, fan-out/fan-in |
| **DSL** | `PipelineBuilder` | `DAGBuilder` |
| **Runs on** | Vertex AI (via Composer) | Composer (Airflow) directly |
| **Components** | `BigQueryExtract`, `TrainModel`, etc. | `BQQueryTask`, `EmailTask`, `VertexPipelineTask` |
| **Airflow code** | None — auto-wrapped | You control the DAG shape |
| **GPU support** | Yes (via `machine_type`) | Via `VertexPipelineTask` |
| **Parallel tasks** | Sequential steps | Arbitrary DAG with `depends_on` |
| **Example** | `churn_prediction` | `sales_analytics`, `recommendation_engine` |

**Hybrid pattern**: Use `dag.py` with `VertexPipelineTask` to orchestrate multiple ML pipelines from a single DAG. See `pipelines/recommendation_engine/` for an example.

---

## What's Next?

| Guide | When to read |
|-------|-------------|
| [Integration Guide](integration.md) | Migrating existing ML code into the framework |
| [Demo Walkthrough](../demo.md) | Full GCP setup: Terraform, Docker, seed data, deploy, verify |
| [Framework Reference](../understanding.md) | Deep dive into every DSL, component, and CLI command |
