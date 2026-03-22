"""DeployModel — deploy a registered model to a Vertex AI Endpoint."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class DeployModel(BaseComponent):
    """Deploy a registered model to a Vertex AI Endpoint as a web service.

    Every model is deployed as its own endpoint. The endpoint display name is
    derived from the naming convention using pipeline name + model name:

        {project}-{branch}-{pipeline}-{model_name}-endpoint

    ``model_name`` must match the value used in ``RegisterModel`` so the
    compiler can derive matching ``model_display_name`` and
    ``endpoint_display_name`` values.

    The model is looked up from the Vertex AI Model Registry by display name —
    the serving container image is already captured during registration.
    ``DeployModel`` does not need any serving image fields.

    See ``docs/deploy.md`` for the full design rationale.

    Args:
        model_name: Short identifier matching ``RegisterModel.model_name``
            (e.g. ``"regression"``). Used to derive both the model display
            name and endpoint display name via naming convention.
        model_display_name: Display name in Model Registry. Auto-derived
            from pipeline + model_name by the compiler.
        endpoint_display_name: Display name of the Vertex AI Endpoint.
            Auto-derived from pipeline + model_name by the compiler.
        machine_type: Compute type for the endpoint.
        min_replica_count: Minimum number of replicas.
        max_replica_count: Maximum number of replicas.
        traffic_split: Traffic routing for canary deployments.

    Example:
        DeployModel(
            model_name="regression",
            traffic_split={"new": 10, "current": 90},
        )
    """

    # Component-specific fields
    model_name: str = ""
    model_display_name: str = ""
    endpoint_display_name: str = ""

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
            model_display_name=self.model_display_name,
            endpoint_display_name=self.endpoint_display_name,
            machine_type=self.machine_type,
            min_replica_count=self.min_replica_count,
            max_replica_count=self.max_replica_count,
            traffic_split=self.traffic_split,
            output_uri_path=self.output_uri_path,
        )


if __name__ == "__main__":
    DeployModel.cli()
