"""RegisterModel — upload a model to the Vertex AI Model Registry."""

from pathlib import Path

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent


class RegisterModel(BaseComponent):
    """
    Upload a trained model to Vertex AI Model Registry.

    Example:
        RegisterModel(
            component_name="register",
            model_uri="gs://bucket/models/churn/latest",
            model_display_name="churn-model",
            serving_container_image="us-central1-docker.pkg.dev/proj/repo/serving:latest",
        )
    """

    model_uri: str = ""
    model_display_name: str = ""
    serving_container_image: str = ""
    labels: dict = Field(default_factory=dict)
    description: str = ""
    component_name: str = "register_model"

    def execute(self):
        from google.cloud import aiplatform

        aiplatform.init(project=self.project, location=self.region)
        model = aiplatform.Model.upload(
            display_name=self.model_display_name,
            artifact_uri=self.model_uri,
            serving_container_image_uri=self.serving_container_image,
            labels=self.labels,
            description=self.description,
        )
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(model.resource_name)


if __name__ == "__main__":
    RegisterModel.cli()
