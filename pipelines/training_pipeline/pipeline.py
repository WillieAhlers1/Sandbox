from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.train_container import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="training_pipeline", schedule="@daily")
    # .ingest(
    #     BigQueryExtract(
    #         query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
    #         output_table="raw_events_extract",
    #     )
    # )
    # .transform(
    #     BQTransform(
    #         sql_file="sql/training_pipeline_features.sql",
    #         output_table="training_pipeline_features",
    #     )
    # )
    # .write_features(
    #     WriteFeatures(
    #         entity="user",
    #         feature_group="training_pipeline_signals",
    #         entity_id_column="user_id",
    #     )
    # )
    .train(
        TrainModel(
            trainer_image="{artifact_registry}/training_pipeline-trainer:latest",
            machine_type="n2-standard-4",
            hyperparameters={
                "project_id": "prj-0n-dta-pt-ai-sandbox",
            }
        )
    )
    # .evaluate(
    #     EvaluateModel(
    #         metrics=["auc", "f1"],
    #         gate={"auc": 0.75},
    #     )
    # )
    # .deploy(
    #     DeployModel(
    #         endpoint_name="training_pipeline-endpoint",
    #     )
    # )
    .build()
)
