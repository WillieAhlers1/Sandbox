# GCP ML Framework

Branch-isolated ML pipelines on Google Cloud Platform.

One Python file per pipeline. One `gml` command to run, deploy, or promote it. Every branch gets its own namespace — so DEV experiments never touch PROD data.

---

## How it works

When you push a branch, the framework automatically derives a namespace from your team, project, and branch name:

```
branch: feature/user-embeddings
namespace: dsci-churn-pred-feature-user-embeddings

GCS:           gs://dsci-churn-pred/feature-user-embeddings/
BigQuery:      dsci_churn_pred_feature_user_embeddings
Feature Store: dsci-churn-pred  (shared per project, views are branch-namespaced)
Vertex AI:     dsci-churn-pred-feature-user-embeddings-{pipeline}
Airflow DAG:   dsci_churn_pred_feature_user_embeddings__{pipeline}
```

Every GCP resource is derived from this namespace — no hardcoding, no collisions.

### Environment lifecycle

| Git state | Environment | GCP project |
|---|---|---|
| `feature/*`, `hotfix/*`, any branch | DEV | `dev_project_id` |
| `main` | STAGING | `staging_project_id` |
| release tag (`v1.2.3`) | PROD | `prod_project_id` |
| `prod/*` branch | PROD-EXP | `prod_project_id` |

---

## Quickstart

### 1. Install

```bash
pip install uv
uv sync
```

### 2. Scaffold a project

```bash
gml init project dsci churn-pred \
  --dev-project my-gcp-project-dev \
  --staging-project my-gcp-project-staging \
  --prod-project my-gcp-project-prod
```

This creates:

```
framework.yaml          ← team/project identity + GCP project IDs
feature_schemas/        ← entity feature definitions (YAML)
pipelines/              ← one directory per pipeline
.github/workflows/      ← CI/CD workflows (dev, stage, promote, teardown)
scripts/bootstrap.sh    ← one-time GCP setup
tests/
```

### 3. Configure

Edit `framework.yaml`:

```yaml
team: dsci
project: churn-pred

gcp:
  dev_project_id: my-gcp-project-dev
  staging_project_id: my-gcp-project-staging
  prod_project_id: my-gcp-project-prod
  region: us-central1
  composer_env: ml-composer-env
  artifact_registry_host: us-central1-docker.pkg.dev
```

### 4. Add a pipeline

```bash
gml init pipeline churn_prediction
```

Edit `pipelines/churn_prediction/pipeline.py`:

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
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
            output_table="churn_raw",
        )
    )
    .transform(
        BQTransform(
            sql_file="sql/churn_features.sql",
            output_table="churn_features",
        )
    )
    .write_features(
        WriteFeatures(entity="user", feature_group="behavioral")
    )
    .train(
        TrainModel(
            trainer_image="{artifact_registry}/churn-trainer:latest",
            machine_type="n1-standard-8",
            hyperparameters={"learning_rate": 0.05, "max_depth": 6},
        )
    )
    .evaluate(
        EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.78})
    )
    .deploy(
        DeployModel(endpoint_name="churn-classifier")
    )
    .build()
)
```

That's the entire pipeline definition. No DAG code. No KFP YAML. No operator wiring.

### 5. Check your context

```bash
gml context show
```

```
GCP ML Framework — context for branch 'feature/churn-v2'

Identity
  team             dsci
  project          churn-pred
  branch (raw)     feature/churn-v2
  branch (slug)    feature-churn-v2
  git_state        DEV

GCP
  project          my-gcp-project-dev
  region           us-central1

Resource Names
  namespace        dsci-churn-pred-feature-churn-v2
  gcs_prefix       gs://dsci-churn-pred/feature-churn-v2/
  bq_dataset       dsci_churn_pred_feature_churn_v2
  feature_store_id dsci-churn-pred
  secret_prefix    dsci-churn-pred-feature-churn-v2
```

### 6. Run locally

No GCP access required. DuckDB and pandas replace BQ and GCS calls.

```bash
gml run churn_prediction --local
```

```bash
# Print the execution plan without running
gml run churn_prediction --local --dry-run
```

Note: `--local` is the default — `gml run churn_prediction` works the same way.

### 7. Run on Vertex AI

```bash
gml run churn_prediction --vertex
gml run churn_prediction --vertex --sync     # wait for completion
gml run --vertex --all                       # run all pipelines
```

### 8. Deploy to Composer

```bash
# Generate DAG files and sync them to the Composer GCS bucket
gml deploy dags

# Upsert Feature Store entity types and feature views
gml deploy features
```

---

## Core concepts

### Naming convention

All resource names are derived from a single `NamingConvention` object. Nothing is hardcoded anywhere in your pipeline code.

```python
from gcp_ml_framework.naming import NamingConvention

nc = NamingConvention(team="dsci", project="churn-pred", branch="feature/xyz")

nc.namespace               # "dsci-churn-pred-feature-xyz"
nc.bq_dataset              # "dsci_churn_pred_feature_xyz"
nc.gcs_prefix              # "gs://dsci-churn-pred/feature-xyz/"
nc.feature_store_id        # "dsci-churn-pred"  (shared across branches)
nc.dag_id("churn_train")   # "dsci_churn_pred_feature_xyz__churn_train"
```

### MLContext

Every component receives an `MLContext`. It carries the resolved GCP project, namespace, region, and naming convention for the current branch. Components never import config directly.

```python
from gcp_ml_framework.config import load_config
from gcp_ml_framework.context import MLContext

cfg = load_config()                  # reads framework.yaml + env vars
ctx = MLContext.from_config(cfg)

ctx.gcp_project                      # "my-gcp-project-dev"
ctx.bq_dataset                       # "dsci_churn_pred_feature_xyz"
ctx.gcs_prefix                       # "gs://dsci-churn-pred/feature-xyz/"
ctx.is_production()                  # False  (DEV branch)
ctx.secret_name("db-password")       # "dsci-churn-pred-feature-xyz-db-password"
```

### PipelineBuilder

The fluent DSL produces a `PipelineDefinition` that is compiled to KFP YAML for Vertex AI and rendered as an Airflow DAG for Composer. The `schedule` parameter is the single source of truth — set it once, it flows through to both.

```python
pipeline = (
    PipelineBuilder(name="my-pipeline", schedule="@daily")
    .ingest(...)
    .transform(...)
    .train(...)
    .evaluate(...)
    .deploy(...)
    .build()
)
```

### Secrets

Reference secrets by a short key in config or pipeline code. They are resolved at runtime from GCP Secret Manager using the branch namespace as a prefix.

```python
# In any config dict or YAML value:
{"db_url": "!secret db-url"}

# At runtime:
from gcp_ml_framework.secrets.client import make_secret_client
client = make_secret_client(ctx)
client.resolve_dict({"db_url": "!secret db-url"})
# → {"db_url": "<actual value of dsci-churn-pred-main-db-url>"}
```

Local development resolves secrets from environment variables instead:

```bash
export GML_SECRET_DB_URL="postgres://localhost/mydb"
```

### Feature schemas

Define features in YAML — the framework handles Feature Store entity creation and schema migration on `gml deploy features`.

```yaml
# feature_schemas/user.yaml
entity: user
id_column: user_id
id_type: STRING
feature_groups:
  behavioral:
    features:
      - name: session_count_7d
        type: INT64
      - name: total_purchases_30d
        type: FLOAT64
```

---

## CLI reference

```
gml init project <team> <project>      Scaffold a new project
gml init pipeline <name>               Add a pipeline to an existing project

gml context show                       Show resolved namespace and resource names

gml run <pipeline> --local             Run pipeline locally (no GCP, default)
gml run <pipeline> --vertex            Compile and submit to Vertex AI
gml run --compile-only [--all]         Compile to KFP YAML only (CI validation)

gml deploy dags                        Generate and sync Airflow DAGs to Composer
gml deploy features [entity ...]       Upsert Feature Store schemas

gml promote --from main --to prod --tag v1.2.3
                                       Promote STAGE artifacts to PROD

gml teardown --branch <branch>         Delete all DEV resources for a branch
```

---

## CI/CD

Four workflows are scaffolded automatically by `gml init project`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci-dev.yaml` | Push to `feature/*` | Lint, test, compile pipelines, deploy DAGs + features to DEV |
| `ci-stage.yaml` | Push to `main` | Full test suite, deploy DAGs + features to STAGE, run pipelines on Vertex AI |
| `promote.yaml` | Push tag `v*` | Copy STAGE artifacts → PROD, sync PROD DAGs |
| `teardown.yaml` | PR closed / daily | Delete ephemeral DEV resources for merged branches |

### One-time GCP setup

Run once per environment (dev/staging/prod):

```bash
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project my-gcp-project-dev --env dev
```

This enables the required APIs, creates a service account with the right roles, and configures Workload Identity Federation for keyless GitHub Actions auth.

Then add the printed values to your GitHub repo secrets:

```
WIF_PROVIDER_DEV=projects/.../providers/github-provider
SA_EMAIL_DEV=gcp-ml-framework-sa@my-gcp-project-dev.iam.gserviceaccount.com
GCP_PROJECT_ID_DEV=my-gcp-project-dev
```

---

## Project layout

```
framework.yaml                  ← team/project identity + per-env GCP project IDs
feature_schemas/
  user.yaml                     ← entity schema definitions
  item.yaml
pipelines/
  churn_prediction/
    pipeline.py                 ← the only file you write per pipeline
    config.yaml                 ← optional pipeline-level config overrides
    sql/
      churn_features.sql
gcp_ml_framework/               ← framework source (not edited by pipeline authors)
  naming.py
  config.py
  context.py
  secrets/
  components/
  pipeline/
  dag/
  feature_store/
  cli/
  utils/
tests/
  unit/
  integration/
scripts/
  bootstrap.sh
.github/workflows/
```

---

## Environment variables

All config can be overridden via environment variables with the `GML_` prefix:

```bash
GML_TEAM=dsci
GML_PROJECT=churn-pred
GML_GCP__DEV_PROJECT_ID=my-gcp-project-dev
GML_GCP__STAGING_PROJECT_ID=my-gcp-project-staging
GML_GCP__PROD_PROJECT_ID=my-gcp-project-prod
GML_GCP__REGION=us-central1
GML_ENV_OVERRIDE=staging          # force a specific environment (useful in CI)
```

Nested config uses double underscore as the delimiter (`GML_GCP__REGION` → `gcp.region`).
