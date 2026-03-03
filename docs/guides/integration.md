# Integrating Existing Code

How to bring your existing ML code into the framework with minimal changes.

## What Changes, What Doesn't

| Your Code | Framework Component | Effort |
|---|---|---|
| SQL queries / data pulls | `BigQueryExtract` / `BQTransform` | Paste SQL in |
| Feature engineering | `BQTransform` (SQL) | Paste SQL in |
| Training script | `TrainModel` (Docker container) | Add 2 CLI args |
| Model evaluation | `EvaluateModel` | Write metrics.json |
| Model deployment | `DeployModel` | None — framework handles it |

## Step 1: Modify Your Training Script

Add two CLI arguments. The framework passes these automatically.

```python
import argparse
import json
import pandas as pd
import xgboost as xgb
import sklearn.metrics as skm

parser = argparse.ArgumentParser()
parser.add_argument("--dataset-path", required=True)  # GCS path to data
parser.add_argument("--model-output", required=True)   # GCS path to save model
args = parser.parse_args()

# Your existing logic — unchanged
df = pd.read_csv(args.dataset_path)
model = xgb.XGBClassifier(...).fit(df.drop("label", axis=1), df["label"])
model.save_model(f"{args.model_output}/model.json")

# Write metrics so EvaluateModel can gate on them
preds = model.predict_proba(df.drop("label", axis=1))[:, 1]
metrics = {"auc": skm.roc_auc_score(df["label"], preds)}
with open(f"{args.model_output}/metrics.json", "w") as f:
    json.dump(metrics, f)
```

## Step 2: Dockerize Your Trainer

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY train.py .
ENTRYPOINT ["python", "train.py"]
```

```bash
docker build -t us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest .
docker push us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest
```

## Step 3: Create Your Pipeline File

Create `pipelines/<name>/pipeline.py`:

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="my_pipeline", schedule="0 6 * * 1")
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{bq_dataset}.source_table` WHERE dt = '{run_date}'",
            output_table="raw_data",
        )
    )
    .transform(
        BQTransform(
            sql="SELECT *, LOG1P(feature_a) AS log_a FROM `{bq_dataset}.raw_data`",
            output_table="features",
        )
    )
    .train(
        TrainModel(
            trainer_image="us-central1-docker.pkg.dev/my-gcp-dev/ml/my-trainer:latest",
            machine_type="n1-standard-8",
            hyperparameters={"learning_rate": 0.05},
        )
    )
    .evaluate(EvaluateModel(metrics=["auc"], gate={"auc": 0.78}))
    .deploy(DeployModel(endpoint_name="my-model"))
    .build()
)
```

`{bq_dataset}` and `{run_date}` are auto-resolved by the framework. No hardcoded project names.

## Step 4: Test Locally

```bash
gml run my_pipeline --local           # DuckDB stubs, no GCP needed
gml run my_pipeline --local --dry-run  # Validate config without executing
gml context show                       # Check resolved namespace and resources
```

## Step 5: Run on Vertex AI

```bash
gml run my_pipeline --vertex          # Async
gml run my_pipeline --vertex --sync   # Wait for completion
```

All resources are scoped to your branch namespace. DEV branches cannot affect STAGING or PROD.

## Step 6: Promote

```bash
# Merge to main → CI deploys to STAGING automatically
# Tag a release → CI promotes STAGING artifacts to PROD
git tag v1.0.0 && git push origin v1.0.0
```

## Config Override Order

```
framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags
```

Override anything per-run:

```bash
GML_GCP__REGION=europe-west1 gml run my_pipeline --local
```
