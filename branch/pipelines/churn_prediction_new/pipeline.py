from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.pipeline.builder import PipelineBuilder

# Set your dataset and artifact registry
BQ_DATASET = "dsci_churn_prediction_gcp_test"
ARTIFACT_REGISTRY = "us-east4-docker.pkg.dev/prj-0n-dta-pt-ai-sandbox"

pipeline = (
    PipelineBuilder(
        name="churn_prediction_vertex",
        schedule="@daily",
        description="Daily churn model training and deployment pipeline on Vertex AI",
        tags=["churn", "classification"],
    )
    # Step 1: Ingest raw user events
    .ingest(
        BigQueryExtract(
            query=f"""
                SELECT
                    CAST(entity_id AS STRING) AS entity_id,
                    session_count_7d,
                    session_count_30d,
                    total_purchases_30d,
                    days_since_last_login,
                    support_tickets_90d,
                    avg_session_duration_s,
                    churned_within_30d AS label
                FROM `{BQ_DATASET}.raw_user_events`
                WHERE event_date = '{'{run_date}'}'
            """,
            output_table="churn_training_raw",
        ),
        name="ingest_raw_events",
    )
    # Step 2: Feature engineering
    .transform(
        BQTransform(
            sql=f"""
                SELECT
                    CAST(entity_id AS STRING) AS entity_id,
                    session_count_7d,
                    session_count_30d,
                    CAST(total_purchases_30d AS FLOAT64) AS total_purchases_30d,
                    COALESCE(SAFE_DIVIDE(session_count_7d, NULLIF(session_count_30d, 0)),0.0) AS session_trend,
                    COALESCE(LN(1 + total_purchases_30d), 0.0) AS log_purchases_30d,
                    COALESCE(days_since_last_login, 0) AS days_since_last_login,
                    COALESCE(support_tickets_90d, 0) AS support_tickets_90d,
                    COALESCE(avg_session_duration_s, 0) AS avg_session_duration_s,
                    label,
                    CURRENT_TIMESTAMP() AS feature_timestamp
                FROM `{BQ_DATASET}.churn_training_raw`
                WHERE entity_id IS NOT NULL
            """,
            output_table="churn_features_engineered",
        ),
        name="engineer_features",
    )
    # Step 3: Write features to feature store
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="behavioral",
            entity_id_column="entity_id",
            feature_time_column="feature_timestamp",
            feature_ids=[
                "session_count_7d",
                "session_count_30d",
                "total_purchases_30d",
                "days_since_last_login",
                "support_tickets_90d",
                "avg_session_duration_s",
                "session_trend",
                "log_purchases_30d",
            ],
        ),
        name="write_user_features",
    )
    # Step 4: Train model
    .train(
        TrainModel(
            # trainer_image=f"{ARTIFACT_REGISTRY}/churn-trainer:latest",
            trainer_image = "us-east4-docker.pkg.dev/prj-0n-dta-pt-ai-sandbox/dsci-churn-prediction/churn-trainer:latest",
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
    # Step 5: Evaluate model
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.33},  # pipeline halts if AUC < 0.75
        ),
        name="evaluate_model",
    )
    # Step 6: Deploy model
    .deploy(
        DeployModel(
            endpoint_name="churn-classifier",
            serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest",
            machine_type="n1-standard-2",
            min_replica_count=1,
            max_replica_count=3,
            traffic_split={"new": 100},
        ),
        name="deploy_churn_model",
    )
    .build()
)
