from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from pipelines.house_price.steps.train_regression_model import HouseTrainModelStep

pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(HouseTrainModelStep(
        component_name="Regression Model",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .add(RegisterModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
        serving_dockerfile="pipelines/house_price/serve.Dockerfile",
    ))
    .add(DeployModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .build()
)
