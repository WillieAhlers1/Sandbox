"""DeployModel — upload a model to Vertex AI Model Registry and deploy to an Endpoint."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class DeployModel(BaseComponent):
    """
    Upload a trained model to Vertex AI Model Registry and deploy it to an Endpoint.

    Supports canary deployments via `traffic_split`.

    Example:
        DeployModel(
            component_name="deploy",
            endpoint_name="churn-v1",
            serving_container_image="us-central1-docker.pkg.dev/my-proj/serving/churn:latest",
            traffic_split={"new": 10, "current": 90},
        )
    """

    # Component-specific fields
    model_uri: str = ""
    model_display_name: str = ""
    endpoint_display_name: str = ""

    endpoint_name: str
    serving_container_image: str = ""
    machine_type: str = "n2-standard-2"
    min_replica_count: int = 1
    max_replica_count: int = 3
    traffic_split: dict[str, int] = Field(default_factory=lambda: {"new": 100})
    component_name: str = "deploy_model"

    def execute(self) -> None:
        """Container lifecycle: call run()."""
        self.run()

    def run(self) -> None:
        """Deploy model to Vertex AI Endpoint. Override for custom deployment logic."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            project=self.project,
            region=self.region,
            model_uri=self.model_uri,
            model_display_name=self.model_display_name,
            endpoint_display_name=self.endpoint_display_name,
            serving_container_image=self.serving_container_image,
            machine_type=self.machine_type,
            min_replica_count=self.min_replica_count,
            max_replica_count=self.max_replica_count,
            traffic_split=self.traffic_split,
            output_uri_path=self.output_uri_path,
        )



if __name__ == "__main__":
    DeployModel.cli()
