from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel
from pipelines.training_pipeline.steps.train_house_model import HouseTrainModelStep

pipeline = (
    PipelineBuilder(name="training_pipeline", schedule="@daily")
    # .ingest(
    #     BigQueryExtract(
    #         component_name="ingest",
    #         query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
    #         output_table="raw_events_extract",
    #     )
    # )
    # .transform(
    #     BQTransform(
    #         component_name="transform",
    #         sql_file="sql/training_pipeline_features.sql",
    #         output_table="training_pipeline_features",
    #     )
    # )
    # .write_features(
    #     WriteFeatures(
    #         component_name="write_features",
    #         entity="user",
    #         feature_group="training_pipeline_signals",
    #         entity_id_column="user_id",
    #     )
    # )
    .step(
        HouseTrainModelStep(
            component_name="train_house_model",
            machine_type="n2-standard-4",
        ),
        name="Train House Price Model",
    )
    .build()
)
