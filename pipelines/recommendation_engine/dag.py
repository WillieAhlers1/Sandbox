"""
Recommendation engine DAG — hybrid with BQ tasks + 2 Vertex pipelines.

Demonstrates the hybrid orchestration pattern: a Composer DAG coordinates
two Vertex AI pipelines (feature engineering + model training) with a BQ
extraction step and email notification.

Flow:
    extract_data → compute_features (Vertex Pipeline 1)
                 → train_model (Vertex Pipeline 2)
                 → notify
"""

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask
from gcp_ml_framework.pipeline.builder import PipelineBuilder

# --- Vertex Pipeline 1: Feature Engineering ---
feature_pipeline = (
    PipelineBuilder(
        name="reco_features",
        description="Feature extraction for recommendation engine",
        tags=["recommendations", "features"],
    )
    .ingest(
        BigQueryExtract(
            query=(
                "SELECT user_id, item_id, interaction_type, ts "
                "FROM `{bq_dataset}.raw_interactions`"
            ),
            output_table="raw_interactions",
        )
    )
    .transform(
        BQTransform(
            sql=(
                "SELECT user_id, item_id, interaction_type, "
                "COUNT(*) AS interaction_count "
                "FROM `{bq_dataset}.raw_interactions` "
                "GROUP BY user_id, item_id, interaction_type"
            ),
            output_table="reco_user_item_features",
        )
    )
    .transform(
        BQTransform(
            sql=(
                "SELECT user_id, "
                "COUNT(DISTINCT item_id) AS unique_items, "
                "SUM(interaction_count) AS total_interactions, "
                "SUM(CASE WHEN interaction_type = 'purchase' "
                "THEN interaction_count ELSE 0 END) AS purchase_count "
                "FROM `{bq_dataset}.reco_user_item_features` "
                "GROUP BY user_id"
            ),
            output_table="reco_user_profiles",
        )
    )
    .write_features(WriteFeatures(entity="user", feature_group="behavioral"))
    .build()
)

# --- Vertex Pipeline 2: Model Training ---
# Note: No evaluate/deploy steps — the NMF recommendation model is incompatible
# with the generic EvaluateModel (expects binary classifier) and DeployModel
# (expects sklearn serving container). Recommendation-specific evaluation and
# serving would require dedicated components.
training_pipeline = (
    PipelineBuilder(
        name="reco_training",
        description="Model training for recommendation engine",
        tags=["recommendations", "training"],
    )
    .ingest(
        BigQueryExtract(
            query=(
                "SELECT user_id, item_id, interaction_type, ts "
                "FROM `{bq_dataset}.raw_interactions`"
            ),
            output_table="reco_training_data",
        )
    )
    .transform(
        BQTransform(
            sql=(
                "SELECT user_id, item_id, interaction_type, ts "
                "FROM `{bq_dataset}.reco_training_data`"
            ),
            output_table="reco_training_prepared",
        )
    )
    .train(
        TrainModel(
            machine_type="n2-standard-16",
            hyperparameters={"embedding_dim": 64, "epochs": 50},
        )
    )
    .build()
)

# --- Orchestration DAG ---
dag = (
    DAGBuilder(
        name="recommendation_engine",
        schedule="0 2 * * *",
        description="Daily recommendation engine: features + model training",
        tags=["ml", "recommendations"],
    )
    .task(
        BQQueryTask(
            sql_file="sql/extract_interactions.sql",
            destination_table="raw_interactions",
        ),
        name="extract_data",
        depends_on=[],
    )
    .task(
        VertexPipelineTask(pipeline=feature_pipeline),
        name="compute_features",
        depends_on=["extract_data"],
    )
    .task(
        VertexPipelineTask(pipeline=training_pipeline),
        name="train_model",
        depends_on=["compute_features"],
    )
    .task(
        EmailTask(
            to=["ml-team@company.com"],
            subject="[{namespace}] Recommendation model updated — {run_date}",
            body=(
                "The recommendation engine pipeline has completed.\n\n"
                "Features pipeline: reco_features\n"
                "Training pipeline: reco_training\n"
                "Execution date: {run_date}"
            ),
        ),
        name="notify",
        depends_on=["train_model"],
    )
    .build()
)
