# Integrating Existing Code

How to bring your existing ML code into the framework with minimal changes.

## What Changes, What Doesn't

| Your Existing Code | Framework Component | Migration Effort |
|---|---|---|
| SQL queries / data pulls | `BigQueryExtract` or `BQTransform` | Paste SQL in |
| Feature engineering (SQL) | `BQTransform` with `sql_file` | Move SQL to file, add template vars |
| Feature engineering (Python) | Keep as-is inside trainer | No change |
| Training script (Python) | `TrainModel` (Docker container) | Add 2 CLI args |
| Model evaluation | `EvaluateModel` | Set metrics + gate thresholds |
| Model deployment | `DeployModel` | None — framework handles it |
| Feature registration | `WriteFeatures` | Specify entity + feature group |
| Airflow DAG | `DAGBuilder` with tasks | Replace operators with tasks |

## Step 1: Modify Your Training Script

Add two CLI arguments. The framework passes these automatically when running on Vertex AI.

```python
import argparse
import json
import pickle

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from google.cloud import bigquery, storage

parser = argparse.ArgumentParser()
parser.add_argument("--dataset-path", required=True)   # BQ table or GCS path
parser.add_argument("--model-output", required=True)    # GCS path to save model
parser.add_argument("--learning-rate", type=float, default=0.05)
parser.add_argument("--max-depth", type=int, default=6)
args = parser.parse_args()

# Load data from BigQuery (or GCS — your choice)
client = bigquery.Client()
df = client.query(f"SELECT * FROM `{args.dataset_path}`").to_dataframe()

# Your existing training logic — unchanged
X = df.drop(columns=["label", "user_id"])
y = df["label"]
model = GradientBoostingClassifier(
    learning_rate=args.learning_rate,
    max_depth=args.max_depth,
).fit(X, y)

# Save model to GCS
bucket_name = args.model_output.replace("gs://", "").split("/")[0]
blob_path = "/".join(args.model_output.replace("gs://", "").split("/")[1:]) + "/model.pkl"
sc = storage.Client()
sc.bucket(bucket_name).blob(blob_path).upload_from_string(pickle.dumps(model))
```

## Step 2: Dockerize Your Trainer

Create `pipelines/{name}/trainer/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY train.py .
ENTRYPOINT ["python", "train.py"]
```

Create `pipelines/{name}/trainer/requirements.txt`:

```
scikit-learn>=1.4
pandas>=2.0
google-cloud-bigquery>=3.17
google-cloud-storage>=2.14
db-dtypes>=1.2
```

**Or skip this step** — if you leave `trainer_image` empty in your `TrainModel`, the framework auto-generates a Dockerfile and derives the image URI from your pipeline name:

```bash
# Auto-build all trainer images
./scripts/docker_build.sh
```

## Step 3: Create Your Pipeline File

Create `pipelines/{name}/pipeline.py`:

```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
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
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="my_features",
            entity_id_column="user_id",
        )
    )
    .train(
        TrainModel(
            machine_type="n2-standard-8",
            hyperparameters={"learning_rate": 0.05, "max_depth": 6},
        )
    )
    .evaluate(
        EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.78})
    )
    .deploy(
        DeployModel(
            endpoint_name="my-model",
            serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest",
        )
    )
    .build()
)
```

Template variables (`{bq_dataset}`, `{run_date}`, `{gcs_prefix}`, `{artifact_registry}`) are auto-resolved by the framework from your git branch.

## Step 4: Add Seed Data for Local Testing

Create `pipelines/{name}/seeds/source_table.csv`:

```csv
user_id,feature_a,feature_b,label
1,10.5,3,1
2,2.1,8,0
3,15.0,1,1
```

The filename (minus extension) becomes the table name in DuckDB. The framework loads it into `{bq_dataset}.source_table` automatically.

## Step 5: Test Locally

```bash
gml run my_pipeline --local             # DuckDB stubs, no GCP needed
gml run my_pipeline --local --dry-run   # validate config without executing
gml context show                        # check resolved namespace and resources
```

Note: `EvaluateModel` returns placeholder metrics (0.50) locally. If your gate threshold is above 0.50, the local run will intentionally fail — this validates your gate configuration works.

## Step 6: Run on Vertex AI

```bash
gml run my_pipeline --vertex            # async
gml run my_pipeline --vertex --sync     # wait for completion
```

All resources are scoped to your branch namespace. DEV branches cannot affect STAGING or PROD.

## Step 7: Deploy

```bash
gml compile my_pipeline                 # compile to KFP YAML + Airflow DAG
gml deploy my_pipeline                  # upload to GCS + Composer
```

## Step 8: Promote

```bash
# Merge to main -> CI deploys to STAGING automatically
# Tag a release -> CI promotes STAGING artifacts to PROD
git tag v1.0.0 && git push origin v1.0.0
```

## Creating a DAG Instead of a Pipeline

If your workflow includes non-ML tasks (ETL, notifications, sensors) or needs parallel execution, use `DAGBuilder` instead of `PipelineBuilder`:

```python
# pipelines/my_etl/dag.py
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(name="my_etl", schedule="0 6 * * *")
    .task(BQQueryTask(sql_file="sql/extract.sql", destination_table="raw"), name="extract", depends_on=[])
    .task(BQQueryTask(sql_file="sql/transform.sql", destination_table="features"), name="transform")
    .task(EmailTask(to=["team@co.com"], subject="[{namespace}] ETL Done"), name="notify")
    .build()
)
```

Place SQL files in `pipelines/my_etl/sql/` and seed CSVs in `pipelines/my_etl/seeds/`.

## Config Override Order

```
framework defaults -> framework.yaml -> pipeline/config.yaml -> env vars -> CLI flags
```

Override anything per-run:

```bash
GML_GCP__REGION=europe-west1 gml run my_pipeline --local
```
