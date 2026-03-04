from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

# IMPORTANT: Infrastructure provisioning is AUTOMATIC
# ================================================
# When you run: gml run churn_prediction --vertex --sync
# The framework automatically executes (in order):
#
# 1. Terraform Apply (from terraform/ folder)
#    - Creates BigQuery dataset
#    - EXECUTES ALL SQL FILES from sql/BQ/ and sql/FS/ folders
#    - Creates Artifact Registry and Cloud Build
#    - Sets up IAM permissions
#
# 2. Docker Build (if trainer is configured)
#    - Builds trainer container
#    - Pushes to Artifact Registry
#
# 3. KFP Compilation & Submission
#    - Compiles pipeline.py to Vertex AI format
#    - Submits to Vertex AI Pipelines
#
# See terraform/README.md for SQL file management and manual provisioning.

pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="@daily")
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
            output_table="raw_events_extract",
        )
    )
    .transform(
        BQTransform(
            sql_file="sql/churn_prediction_features.sql",
            output_table="churn_prediction_features",
        )
    )
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="churn_prediction_signals",
            entity_id_column="user_id",
        )
    )
    .train(
        TrainModel(
            trainer_image="{artifact_registry}/churn_prediction-trainer:latest",
            machine_type="n1-standard-4",
        )
    )
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.75},
        )
    )
    .deploy(
        DeployModel(
            endpoint_name="churn_prediction-endpoint",
        )
    )
    .build()
)
