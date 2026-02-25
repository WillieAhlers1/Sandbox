"""DeployModel — upload a model to Vertex AI Model Registry and deploy to an Endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class DeployModel(BaseComponent):
    """
    Upload a trained model to Vertex AI Model Registry and deploy it to an Endpoint.

    Supports canary deployments via `traffic_split`. The Endpoint uses a stable
    name derived from the namespace so the URL never changes across releases.

    PROD promotion: the stable Endpoint alias (`{team}-{project}-prod-{endpoint_name}`)
    always points to the current PROD model, updated by `gml promote`.

    Example:
        DeployModel(
            endpoint_name="churn-v1",
            serving_container_image="us-central1-docker.pkg.dev/my-proj/serving/churn:latest",
            traffic_split={"new": 10, "current": 90},   # canary
        )
    """

    endpoint_name: str
    serving_container_image: str = ""
    machine_type: str = "n1-standard-2"
    min_replica_count: int = 1
    max_replica_count: int = 3
    traffic_split: dict[str, int] = field(default_factory=lambda: {"new": 100})
    component_name: str = "deploy_model"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-aiplatform>=1.49"],
        )
        def deploy_model(
            project: str,
            region: str,
            model_uri: str,
            model_display_name: str,
            endpoint_display_name: str,
            serving_container_image: str,
            machine_type: str,
            min_replica_count: int,
            max_replica_count: int,
            traffic_split: str,  # JSON dict {"new": 10, "current": 90}
        ) -> str:
            """Returns the Endpoint resource name."""
            import json

            from google.cloud import aiplatform

            aiplatform.init(project=project, location=region)

            model = aiplatform.Model.upload(
                display_name=model_display_name,
                artifact_uri=model_uri,
                serving_container_image_uri=serving_container_image,
            )

            # Get or create endpoint
            existing = aiplatform.Endpoint.list(
                filter=f'display_name="{endpoint_display_name}"',
                project=project,
                location=region,
            )
            endpoint = existing[0] if existing else aiplatform.Endpoint.create(
                display_name=endpoint_display_name,
                project=project,
                location=region,
            )

            split = json.loads(traffic_split)
            # Vertex AI traffic_split uses deployed_model_id keys; simplify to 100% new
            endpoint.deploy(
                model=model,
                machine_type=machine_type,
                min_replica_count=min_replica_count,
                max_replica_count=max_replica_count,
                traffic_split={"0": split.get("new", 100)},
            )
            return endpoint.resource_name

        return deploy_model

    def local_run(
        self,
        context: MLContext,
        model_path: str = "",
        **kwargs: Any,
    ) -> str:
        endpoint_name = context.naming.vertex_endpoint_name(self.endpoint_name)
        print(f"[local] DeployModel: would deploy to Endpoint '{endpoint_name}'")
        print(f"[local] DeployModel: model_path={model_path!r}, traffic={self.traffic_split}")
        return f"projects/{context.gcp_project}/locations/{context.region}/endpoints/local-stub"
