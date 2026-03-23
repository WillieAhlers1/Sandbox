"""Verification pipeline — exercises ALL framework capabilities.

Structure:
    BQQuery (@task)       → ingest raw data
    BQTransform (@task)   → transform features
    TrainVerifyModelStep  → train (@ml_task)
    EvaluateVerifyStep    → evaluate with gates (@ml_task)
    for_each              → train per-market variants (@ml_task loop, REQS 22.0)
    condition             → register + deploy if eval passed (@ml_task condition, REQS 22.0)

What this proves:
    - Pipeline.add() with mixed @task + @ml_task
    - SmartCompiler groups: [TASK ×2] → DAG operators + [ML_TASK ×2] → KFP YAML
    - for_each() → KFP ParallelFor (trains per-market variants)
    - condition() → KFP If (gates register + deploy on eval output)
    - Cross-step data wiring through the ML group + into condition branches
    - Full ML lifecycle: ingest → transform → train → evaluate
      → loop → condition(register → deploy)
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
    # --- Sequential @task steps (Airflow operators) ---
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
    # --- Sequential @ml_task steps (KFP) ---
    .add(
        TrainVerifyModelStep(
            component_name="train_verify_model",
            machine_type="n2-standard-4",
            runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
        ),
        name="Train Model",
    )
    .add(
        EvaluateVerifyStep(
            metrics=["rmse", "mae", "r2"],
            gate={"rmse": 1_000_000},
            component_name="evaluate_verify_model",
            runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
        ),
        name="Evaluate Model",
    )
    # --- Loop: train per-market variants (REQS 22.0) ---
    .for_each(
        items=["us-market", "eu-market"],
        steps=[
            TrainVerifyModelStep(
                component_name="train_market_variant",
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
            ),
        ],
        item_param="job_name",
    )
    # --- Condition: only register+deploy if eval passed (REQS 22.0) ---
    .condition(
        source_step="Evaluate Model",
        operator="!=",
        value="",
        then_steps=[
            RegisterModel(
                model_name="verification-predictor",
                component_name="register_model",
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
                serving_dockerfile="pipelines/verification_pipeline/serve.Dockerfile",
            ),
            DeployModel(
                model_name="verification-predictor",
                machine_type="n2-standard-2",
                min_replica_count=1,
                max_replica_count=1,
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
                enable_monitoring=True,
                monitoring_alert_email="team@example.com",
                monitoring_skew_thresholds={"area": 0.3, "bedrooms": 0.3},
                component_name="deploy_model",
            ),
        ],
    )
    .build()
)
