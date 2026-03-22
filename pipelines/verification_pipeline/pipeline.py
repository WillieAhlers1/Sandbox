"""Verification pipeline — mixed @task + @ml_task to prove SmartCompiler works.

Structure:
    BQQuery (ingest) → BQTransform (transform) → TrainVerifyModelStep (train)
    → EvaluateVerifyStep (evaluate) → RegisterModel (register) → DeployModel (deploy)

What this proves:
    - Pipeline.add() with mixed @task + @ml_task
    - SmartCompiler groups: [TASK, TASK] → DAG operators + [ML_TASK × 4] → KFP YAML
    - Full ML lifecycle: ingest → transform → train → evaluate → register → deploy
    - Cross-step data wiring (model_uri, dataset_uri) through the ML group
    - Smart model resolution in deploy (uses registered model resource_name)
"""

from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from pipelines.verification_pipeline.steps.evaluate_verify_model import (
    EvaluateVerifyStep,
)
from pipelines.verification_pipeline.steps.train_verify_model import (
    TrainVerifyModelStep,
)

pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    .add(
        BQQuery(
            sql=(
                "SELECT * FROM `{bq_dataset}.housing_data_table`"
                " WHERE 1=1"
            ),
            destination_table="verification_raw",
            component_name="ingest_raw",
        ),
        name="Ingest Raw Data",
    )
    .add(
        BQTransform(
            sql=(
                "SELECT *, CURRENT_TIMESTAMP() AS processed_at"
                " FROM `{bq_dataset}.verification_raw`"
            ),
            output_table="verification_features",
            component_name="transform_features",
        ),
        name="Transform Features",
    )
    .add(
        TrainVerifyModelStep(
            component_name="train_verify_model",
            machine_type="n2-standard-4",
        ),
        name="Train Model",
    )
    .add(
        EvaluateVerifyStep(
            metrics=["rmse", "mae", "r2"],
            gate={"rmse": 1_000_000},
            component_name="evaluate_verify_model",
        ),
        name="Evaluate Model",
    )
    .add(
        RegisterModel(
            component_name="register_model",
        ),
        name="Register Model",
    )
    .add(
        DeployModel(
            endpoint_name="verification-predictor",
            machine_type="n2-standard-2",
            min_replica_count=1,
            max_replica_count=1,
            enable_monitoring=True,
            monitoring_alert_email="team@example.com",
            monitoring_skew_thresholds={"area": 0.3, "bedrooms": 0.3},
            component_name="deploy_model",
        ),
        name="Deploy Model",
    )
    .build()
)
