"""Reusable Vertex AI deployment logic — extracted from deploy component."""

from __future__ import annotations

import json
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
