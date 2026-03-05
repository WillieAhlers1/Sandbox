"""
Recommendation training pipeline.

Trains the collaborative filtering model for the recommendation engine.
Referenced by the recommendation_engine DAG as a VertexPipelineTask.
"""

from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.pipeline.builder import PipelineBuilder

pipeline = (
    PipelineBuilder(
        name="reco_training",
        schedule=None,  # triggered by DAG, not scheduled directly
        description="Model training for recommendation engine",
        tags=["recommendations", "training"],
    )
    .ingest(
        BigQueryExtract(
            query="""
                SELECT
                    user_id,
                    item_id,
                    interaction_type,
                    ts
                FROM `{bq_dataset}.staged_interactions`
            """,
            output_table="reco_training_data",
        ),
        name="extract_training_data",
    )
    .train(
        TrainModel(
            machine_type="n2-standard-4",
            hyperparameters={
                "n_components": 10,
                "max_iter": 200,
            },
        ),
        name="train_reco_model",
    )
    .build()
)
