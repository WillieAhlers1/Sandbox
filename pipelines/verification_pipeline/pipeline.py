"""Verification pipeline — mixed @task + @ml_task to prove SmartCompiler works.

Structure:
    BQQuery (ingest) → BQTransform (transform) → TrainVerifyModelStep (train)

What this proves:
    - Pipeline.add() with mixed @task + @ml_task
    - SmartCompiler groups: [TASK, TASK] → DAG operators + [ML_TASK] → KFP YAML
    - BQQuery.render_operator() → BigQueryInsertJobOperator
    - BQTransform.render_operator() → BigQueryInsertJobOperator
    - TrainModel subclass → KFP container component
"""

from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
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
    .build()
)
