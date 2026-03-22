"""RegisterModel — upload a model to the Vertex AI Model Registry."""

from pathlib import Path

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task

@ml_task
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
    labels: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    component_name: str = "register_model"

    def execute(self) -> None:
        """Container lifecycle: call run(), write output URI."""
        resource_name = self.run()
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(resource_name)

    def run(self) -> str:
        """Register model in Vertex AI Model Registry. Override for custom registration.

        Returns:
            The registered model's resource name.
        """
        from google.cloud import aiplatform

        aiplatform.init(project=self.project, location=self.region)
        upload_kwargs: dict = {
            "display_name": self.model_display_name,
            "artifact_uri": self.model_uri,
            "serving_container_image_uri": self.serving_container_image,
            "labels": self.labels,
            "description": self.description,
        }
        # CPR config for custom serving containers (not pre-built Vertex AI images)
        if not self.serving_container_image.startswith(
            "us-docker.pkg.dev/vertex-ai/"
        ):
            upload_kwargs.update({
                "serving_container_predict_route": "/predict",
                "serving_container_health_route": "/health",
                "serving_container_command": [
                    "python", "-m", "gcp_ml_framework.serving.handler",
                ],
                "serving_container_ports": [8080],
            })
        model = aiplatform.Model.upload(**upload_kwargs)
        return model.resource_name


if __name__ == "__main__":
    RegisterModel.cli()
