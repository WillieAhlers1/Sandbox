from gcp_ml_framework import Pipeline
from pipelines.house_price.steps.train_regression_model import HouseTrainModelStep
from gcp_ml_framework.components.ml.register import RegisterModel

pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(HouseTrainModelStep(component_name="Regression Model"))
    .add(RegisterModel(model_name="regression"))
    .build()
)
