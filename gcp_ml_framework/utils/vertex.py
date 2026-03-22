"""Reusable Vertex AI deployment logic — extracted from deploy component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_deploy(
    *,
    project: str,
    region: str,
    model_uri: str,
    model_display_name: str,
    endpoint_display_name: str,
    serving_container_image: str,
    machine_type: str,
    min_replica_count: int,
    max_replica_count: int,
    traffic_split: dict[str, int],
    output_uri_path: str,
) -> None:
    """Upload a model to Vertex AI Model Registry and deploy to an Endpoint."""
    from google.cloud import aiplatform

    aiplatform.init(project=project, location=region)

    # Create a new version under an existing model if one exists
    parent_model = None
    existing_models = aiplatform.Model.list(
        filter=f'display_name="{model_display_name}"',
        project=project,
        location=region,
    )
    if existing_models:
        parent_model = existing_models[0].resource_name
        logger.info(
            f"Found existing model '{model_display_name}' — "
            f"creating new version under {parent_model}"
        )

    upload_kwargs: dict = {
        "display_name": model_display_name,
        "artifact_uri": model_uri,
        "serving_container_image_uri": serving_container_image,
    }
    if parent_model:
        upload_kwargs["parent_model"] = parent_model
        upload_kwargs["is_default_version"] = True

    # Deploy needs the model to be fully registered, so we must wait (sync=True).
    model = aiplatform.Model.upload(**upload_kwargs)

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
