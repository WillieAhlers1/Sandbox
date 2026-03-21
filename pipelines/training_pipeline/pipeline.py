from gcp_ml_framework import Pipeline
from pipelines.training_pipeline.steps.train_house_model import HouseTrainModelStep

pipeline = (
    Pipeline(name="training_pipeline", schedule="@daily")
    .add(
        HouseTrainModelStep(
            component_name="train_house_model",
            machine_type="n2-standard-4",
        ),
        name="Train House Price Model",
    )
    .build()
)
