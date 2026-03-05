"""
Recommendation features pipeline.

Extracts and transforms user/item features for the recommendation engine.
Referenced by the recommendation_engine DAG as a VertexPipelineTask.
"""

from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.pipeline.builder import PipelineBuilder

pipeline = (
    PipelineBuilder(
        name="reco_features",
        schedule=None,  # triggered by DAG, not scheduled directly
        description="Feature extraction for recommendation engine",
        tags=["recommendations", "features"],
    )
    .ingest(
        BigQueryExtract(
            query="""
                SELECT
                    user_id,
                    item_id,
                    interaction_type,
                    COUNT(*) AS interaction_count
                FROM `{bq_dataset}.staged_interactions`
                GROUP BY user_id, item_id, interaction_type
            """,
            output_table="reco_user_item_features",
        ),
        name="extract_user_item_features",
    )
    .transform(
        BQTransform(
            sql="""
                SELECT
                    user_id,
                    COUNT(DISTINCT item_id) AS unique_items,
                    SUM(interaction_count) AS total_interactions,
                    SUM(CASE WHEN interaction_type = 'purchase' THEN interaction_count ELSE 0 END) AS purchase_count
                FROM `{bq_dataset}.reco_user_item_features`
                GROUP BY user_id
            """,
            output_table="reco_user_profiles",
        ),
        name="build_user_profiles",
    )
    .build()
)
