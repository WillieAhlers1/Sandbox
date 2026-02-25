"""
Example churn prediction pipeline.

This is the reference pipeline for the GCP ML Framework.
Edit this file to change the pipeline topology — no DAG code required.
"""

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.pipeline.builder import PipelineBuilder

pipeline = (
    PipelineBuilder(
        name="churn_prediction",
        schedule="0 6 * * 1",    # every Monday at 06:00 UTC
        description="Weekly churn model training and deployment pipeline",
        tags=["churn", "classification"],
    )
    .ingest(
        BigQueryExtract(
            query="""
                SELECT
                    user_id,
                    session_count_7d,
                    session_count_30d,
                    total_purchases_30d,
                    days_since_last_login,
                    support_tickets_90d,
                    avg_session_duration_s,
                    CASE WHEN churned_within_30d THEN 1 ELSE 0 END AS label
                FROM `{bq_dataset}.raw_user_events`
                WHERE event_date BETWEEN DATE_SUB('{run_date}', INTERVAL 90 DAY) AND '{run_date}'
            """,
            output_table="churn_training_raw",
        ),
        name="ingest_raw_events",
    )
    .transform(
        BQTransform(
            sql="""
                SELECT
                    user_id,
                    session_count_7d,
                    session_count_30d,
                    CAST(total_purchases_30d AS FLOAT64) AS total_purchases_30d,
                    SAFE_DIVIDE(session_count_7d, NULLIF(session_count_30d, 0)) AS session_trend,
                    LN(1 + total_purchases_30d) AS log_purchases_30d,
                    days_since_last_login,
                    support_tickets_90d,
                    avg_session_duration_s,
                    label,
                    CURRENT_TIMESTAMP() AS feature_timestamp
                FROM `{bq_dataset}.churn_training_raw`
                WHERE user_id IS NOT NULL
            """,
            output_table="churn_features_engineered",
        ),
        name="engineer_features",
    )
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="behavioral",
            entity_id_column="user_id",
            feature_time_column="feature_timestamp",
            feature_ids=[
                "session_count_7d",
                "session_count_30d",
                "total_purchases_30d",
                "days_since_last_login",
                "support_tickets_90d",
                "avg_session_duration_s",
            ],
        ),
        name="write_user_features",
    )
    .train(
        TrainModel(
            trainer_image="{artifact_registry}/churn-trainer:latest",
            machine_type="n1-standard-8",
            hyperparameters={
                "learning_rate": 0.05,
                "max_depth": 6,
                "n_estimators": 300,
                "subsample": 0.8,
            },
        ),
        name="train_churn_model",
    )
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.78},   # pipeline halts if AUC < 0.78
        ),
        name="evaluate_model",
    )
    .deploy(
        DeployModel(
            endpoint_name="churn-classifier",
            serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest",
            machine_type="n1-standard-2",
            min_replica_count=1,
            max_replica_count=3,
            traffic_split={"new": 100},
        ),
        name="deploy_churn_model",
    )
    .build()
)
