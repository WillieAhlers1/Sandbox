"""Training pipeline — full ML lifecycle for house price prediction.

Structure:
    BQQuery (ingest) → BQTransform (transform) → HouseTrainModelStep (train)
    → HouseEvaluateStep (evaluate) → RegisterModel (register) → DeployModel (deploy)

What this proves:
    - Full 6-step ML lifecycle
    - SmartCompiler groups: [TASK, TASK] → DAG operators + [ML_TASK × 4] → KFP YAML
    - Cross-step data wiring through the ML group
"""

from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from pipelines.training_pipeline.steps.evaluate_house_model import (
    HouseEvaluateStep,
)
from pipelines.training_pipeline.steps.train_house_model import HouseTrainModelStep

pipeline = (
    Pipeline(name="training_pipeline", schedule="@daily")
    .add(
        BQQuery(
            sql="SELECT * FROM `{bq_dataset}.housing_data_table`",
            destination_table="training_raw",
            component_name="ingest_raw_data",
        ),
        name="Ingest Raw Data",
    )
    .add(
        BQTransform(
            sql=(
                "SELECT *, CURRENT_TIMESTAMP() AS processed_at"
                " FROM `{bq_dataset}.training_raw`"
            ),
            output_table="training_features",
            component_name="transform_features",
        ),
        name="Transform Features",
    )
    .add(
        HouseTrainModelStep(
            component_name="train_house_model",
            machine_type="n2-standard-4",
        ),
        name="Train Model",
    )
    .add(
        HouseEvaluateStep(
            metrics=["rmse", "mae", "r2"],
            gate={"rmse": 1_000_000},
            component_name="evaluate_house_model",
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
            endpoint_name="housing-predictor",
            machine_type="n2-standard-2",
            min_replica_count=1,
            max_replica_count=1,
            component_name="deploy_model",
        ),
        name="Deploy Model",
    )
    .build()
)
