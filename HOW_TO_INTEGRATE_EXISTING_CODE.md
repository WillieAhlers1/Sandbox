# How to Integrate Your Existing ML Code with the GCP ML Framework

This guide is for Data Scientists who already have working code for data ingestion,
model training, and deployment, and want to adopt the GCP ML Framework with **minimal
refactoring**.

The framework is designed around a key principle: **your existing training and inference
code doesn't need to change** — you wrap it in a Docker container and wire it into the
pipeline DSL. Everything else (GCP resource naming, environment routing, Feature Store
sync, KFP compilation, Airflow DAG generation) is handled by the framework.

---

## Integration Overview

Map your existing code to the framework's pipeline stages:

| Your Existing Code | Framework Component | Refactoring Level |
|---|---|---|
| SQL queries / data pulls | `BigQueryExtract` / `BQTransform` | **Low** — paste your SQL in |
| Feature engineering scripts | `BQTransform` (SQL) or `PandasTransform` (Python) | **Low-to-Medium** |
| Model training script | `TrainModel` (Docker container) | **Very Low** — just add two CLI args |
| Model evaluation | `EvaluateModel` | **Low** — output metrics to a JSON file |
| Model deployment | `DeployModel` | **Near zero** — framework handles this |

---

## Step 1: Initialize the Project

If the project isn't already set up, run:

```bash
gml init project <team> <project-name> \
  --dev-project my-gcp-dev \
  --staging-project my-gcp-staging \
  --prod-project my-gcp-prod
```

This generates `framework.yaml`. Verify the values match your GCP setup:

```yaml
# framework.yaml
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

Create a `.env` file for local development (never commit this):

```bash
GML_TEAM=dsci
GML_PROJECT=churn-pred
GML_GCP__DEV_PROJECT_ID=my-gcp-project-dev
```

---

## Step 2: Package Your Training Code as a Docker Container

This is the most important step and requires the **least refactoring**. Your existing
training script only needs to accept two additional CLI arguments — everything else stays
the same.

**Your existing `train.py` (before):**

```python
import pandas as pd
import xgboost as xgb

df = pd.read_csv("data/features.csv")
model = xgb.XGBClassifier(...).fit(df.drop("label", axis=1), df["label"])
model.save_model("model/model.json")
```

**Your `train.py` (after — minimal change):**

```python
import argparse
import json
import pandas as pd
import xgboost as xgb
import sklearn.metrics as skm

parser = argparse.ArgumentParser()
# Add these two arguments — the framework passes them automatically
parser.add_argument("--dataset-path", required=True)  # GCS path to training data
parser.add_argument("--model-output", required=True)  # GCS path to save model
args = parser.parse_args()

# Your existing logic, unchanged
df = pd.read_csv(args.dataset_path)
model = xgb.XGBClassifier(...).fit(df.drop("label", axis=1), df["label"])

# Save to the output path the framework provides
model.save_model(f"{args.model_output}/model.json")

# Write a metrics JSON so EvaluateModel can gate on them
preds = model.predict_proba(df.drop("label", axis=1))[:, 1]
metrics = {"auc": skm.roc_auc_score(df["label"], preds)}
with open(f"{args.model_output}/metrics.json", "w") as f:
    json.dump(metrics, f)
```

**Dockerfile** (add to your training code directory):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY train.py .
ENTRYPOINT ["python", "train.py"]
```

Build and push to Artifact Registry:

```bash
docker build -t us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest .
docker push us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest
```

---

## Step 3: Create Your Pipeline File

Create `pipelines/<your_pipeline>/pipeline.py`. This is the **only new file you write
for the framework**. Map each stage of your existing workflow to a component, pasting in
your existing SQL queries directly.

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(
        name="my_pipeline",
        schedule="0 6 * * 1",  # Weekly on Mondays — or remove for manual-only
    )

    # STEP 1: DATA INGESTION
    # Paste your existing SQL query here.
    # {bq_dataset} is auto-resolved to the branch-namespaced dataset —
    # no hardcoded project names needed.
    .ingest(
        BigQueryExtract(
            query="""
                SELECT user_id, feature_a, feature_b, label
                FROM `{bq_dataset}.your_existing_source_table`
                WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
            """,
            output_table="raw_training_data",
        )
    )

    # STEP 2: FEATURE ENGINEERING
    # Paste your existing feature SQL here. {bq_dataset} is auto-injected.
    .transform(
        BQTransform(
            sql="""
                SELECT user_id,
                       LOG1P(feature_a) AS log_feature_a,
                       feature_b / NULLIF(feature_c, 0) AS feature_ratio,
                       label
                FROM `{bq_dataset}.raw_training_data`
            """,
            output_table="engineered_features",
        )
    )

    # STEP 3: MODEL TRAINING
    # Points to your Dockerized training script (Step 2).
    # The framework passes --dataset-path and --model-output automatically.
    .train(
        TrainModel(
            trainer_image="us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest",
            machine_type="n1-standard-8",
            hyperparameters={"learning_rate": 0.05, "n_estimators": 300},
        )
    )

    # STEP 4: EVALUATION
    # Reads metrics.json your trainer wrote. Halts the pipeline if the gate fails.
    .evaluate(
        EvaluateModel(
            metrics=["auc"],
            gate={"auc": 0.78},  # Pipeline halts if AUC < 0.78
        )
    )

    # STEP 5: DEPLOYMENT
    # Framework handles uploading to Model Registry and deploying to an endpoint.
    .deploy(
        DeployModel(
            endpoint_name="my-model-endpoint",
            machine_type="n1-standard-2",
            min_replica_count=1,
            max_replica_count=5,
            traffic_split={"new": 10, "current": 90},  # 10% canary rollout
        )
    )
    .build()
)
```

### Key Concept: `{bq_dataset}` and Resource Naming

The framework automatically derives all GCP resource names from your git branch:

```
Git branch:   feature/my-experiment
Team:         dsci
Project:      churn-pred

→ BQ dataset:    dsci_churn_pred_feature_my_experiment
→ GCS prefix:    gs://dsci-churn-pred/feature-my-experiment/
→ Vertex Exp:    dsci-churn-pred-feature-my-experiment-my-pipeline-exp
```

This means DEV experiments on feature branches **can never touch STAGING or PROD data**
by accident. No environment flags to manage — it's all derived from git state.

---

## Step 4: Test Locally First (No GCP Required)

Before touching any GCP resources, run the pipeline locally. The framework substitutes
BigQuery with DuckDB and skips the Feature Store entirely:

```bash
# Validate config and component wiring — executes nothing
gml run local my_pipeline --dry-run

# Full local run with DuckDB/pandas stubs
gml run local my_pipeline
```

Iterate here until the pipeline runs end-to-end. This catches configuration errors and
logic bugs without spending GCP compute or waiting for Vertex AI job queues.

You can also inspect what the framework has resolved before running:

```bash
gml context show
# Prints: namespace, bq_dataset, gcs_prefix, gcp_project, git_state, etc.
```

---

## Step 5: Run on Vertex AI (DEV)

Once local runs succeed, submit to Vertex AI against your DEV GCP project:

```bash
# Async — submits the job and returns immediately
gml run vertex my_pipeline

# Synchronous — waits for completion and streams logs (useful for debugging)
gml run vertex my_pipeline --sync
```

All resources are automatically scoped to your branch namespace. You cannot accidentally
affect STAGING or PROD.

---

## Step 6: Promote to STAGING and PROD

Promotion is tied to git state — no manual steps required beyond merging and tagging:

```bash
# Merge your feature branch → main
# CI automatically runs: gml deploy dags && gml run vertex ... on STAGING

# Create a release tag to promote to PROD
git tag v1.2.3
git push origin v1.2.3
# CI automatically runs: gml promote --from main --to prod --tag v1.2.3
```

| Git State | Environment | GCP Project | Lifecycle |
|---|---|---|---|
| `feature/*`, any branch | DEV | `dev_project_id` | Ephemeral — deleted on merge |
| `main` | STAGING | `staging_project_id` | Persistent — deployed on every merge |
| Release tag `v*` | PROD | `prod_project_id` | Immutable — manual tag-based promotion |

---

## Special Case: Python-Only Feature Engineering (No SQL)

If your feature engineering is pandas-based rather than SQL, use `PandasTransform` for
local development. Your existing function needs only a `ctx` parameter added:

```python
from gcp_ml_framework.components.transformation.pandas_transform import PandasTransform
import numpy as np

# Your existing function — just add the ctx parameter signature
def my_feature_fn(df: pd.DataFrame, ctx) -> pd.DataFrame:
    # Your existing pandas logic, completely unchanged
    df["log_feature_a"] = np.log1p(df["feature_a"])
    df["feature_ratio"] = df["feature_b"] / df["feature_c"].replace(0, float("nan"))
    return df

# In pipeline.py, use PandasTransform instead of BQTransform
.transform(
    PandasTransform(
        transform_fn=my_feature_fn,
        output_table="engineered_features",
    )
)
```

> **Note:** `PandasTransform` runs locally only. For production Vertex AI runs, convert
> the logic to a `BQTransform` SQL query. Use `PandasTransform` first to validate your
> logic quickly, then migrate to SQL for production.

---

## Configuration Resolution Order

If you need to override settings, the framework resolves config in this order (later
wins):

```
1. Framework defaults (built-in)
2. framework.yaml           (project-level)
3. pipelines/<name>/config.yaml  (pipeline-level overrides)
4. Environment variables    (GML_* prefix)
5. CLI flags                (--flags passed at runtime)
```

Example: override the GCP region for a single run without editing any file:

```bash
GML_GCP__REGION=europe-west1 gml run local my_pipeline
```

---

## Summary: What You Actually Changed

| Task | Effort |
|---|---|
| Add `--dataset-path` and `--model-output` CLI args to `train.py` | ~5 lines |
| Write `metrics.json` at the end of training | ~5 lines |
| Write a `Dockerfile` for your trainer | ~8 lines |
| Create `pipelines/<name>/pipeline.py` | ~40–60 lines (mostly your existing SQL) |
| Fill out `framework.yaml` | ~15 lines |
| Paste your existing SQL into `BigQueryExtract` / `BQTransform` | Zero new SQL — copy/paste |

Your core ML logic — feature engineering, training algorithm, hyperparameters, model
architecture — is **untouched**. The framework handles all infrastructure concerns behind
the scenes.
