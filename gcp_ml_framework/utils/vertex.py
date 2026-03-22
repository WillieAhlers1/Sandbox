"""Reusable Vertex AI deployment logic — extracted from deploy component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_deploy(
    *,
    project: str,
    region: str,
    model_display_name: str,
    endpoint_display_name: str,
    machine_type: str,
    min_replica_count: int,
    max_replica_count: int,
    traffic_split: dict[str, int],
    output_uri_path: str,
) -> None:
    """Look up a registered model and deploy it to a Vertex AI Endpoint.

    The model must already be registered (via RegisterModel) — the serving
    container image is captured during registration and does not need to be
    provided here.
    """
    from google.cloud import aiplatform

    aiplatform.init(project=project, location=region)

    # Look up the registered model by display name
    existing_models = aiplatform.Model.list(
        filter=f'display_name="{model_display_name}"',
        project=project,
        location=region,
    )
    if not existing_models:
        raise ValueError(
            f"No registered model found with display_name='{model_display_name}'. "
            "Ensure RegisterModel runs before DeployModel."
        )

    model = existing_models[0]
    logger.info(f"Found registered model: {model.resource_name}")

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

    endpoint.deploy(
        model=model,
        machine_type=machine_type,
        min_replica_count=min_replica_count,
        max_replica_count=max_replica_count,
        traffic_split={"0": traffic_split.get("new", 100)},
    )
    logger.info(f"Deployed to endpoint {endpoint.resource_name}")

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_uri_path, "w") as f:
        f.write(endpoint.resource_name)
