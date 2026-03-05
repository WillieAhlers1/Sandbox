"""
Recommendation engine DAG — hybrid with BQ tasks + 2 Vertex pipelines.

Flow:
    extract_interactions → [reco_features pipeline, reco_training pipeline] → notify
"""

from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

dag = (
    DAGBuilder(
        name="recommendation_engine",
        schedule="0 4 * * *",  # every day at 04:00 UTC
        description="Daily recommendation engine: features + model training",
        tags=["ml", "recommendations"],
    )
    .task(
        BQQueryTask(
            sql_file="sql/extract_interactions.sql",
            destination_table="staged_interactions",
        ),
        name="extract_interactions",
        depends_on=[],
    )
    .task(
        VertexPipelineTask(pipeline_name="reco_features"),
        name="run_feature_pipeline",
        depends_on=["extract_interactions"],
    )
    .task(
        VertexPipelineTask(pipeline_name="reco_training"),
        name="run_training_pipeline",
        depends_on=["extract_interactions"],
    )
    .task(
        EmailTask(
            to=["ml-team@company.com"],
            subject="[{namespace}] Recommendation Engine Complete — {run_date}",
            body=(
                "The recommendation engine pipeline has completed.\n\n"
                "Features pipeline: reco_features\n"
                "Training pipeline: reco_training\n"
                "Execution date: {run_date}"
            ),
        ),
        name="notify",
        depends_on=["run_feature_pipeline", "run_training_pipeline"],
    )
    .build()
)
