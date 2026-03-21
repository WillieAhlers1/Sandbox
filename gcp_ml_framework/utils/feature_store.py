"""Reusable Feature Store logic — extracted from write_features component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_write_features(
    *,
    project: str,
    region: str,
    feature_group_id: str,
    bq_source_table: str,
    entity_id_column: str,
    output_uri_path: str,
) -> None:
    """Register a BQ table as a Vertex AI Feature Store v2 FeatureGroup."""
    from google.cloud import aiplatform

    aiplatform.init(project=project, location=region)

    from google.cloud.aiplatform_v1beta1 import FeatureRegistryServiceClient
    from google.cloud.aiplatform_v1beta1.types import (
        feature_group as feature_group_pb2,
    )
    from google.cloud.aiplatform_v1beta1.types import (
        feature_registry_service,
    )

    api_endpoint = f"{region}-aiplatform.googleapis.com"
    client = FeatureRegistryServiceClient(
        client_options={"api_endpoint": api_endpoint},
    )
    parent = f"projects/{project}/locations/{region}"
    feature_group_name = f"{parent}/featureGroups/{feature_group_id}"

    try:
        fg = client.get_feature_group(name=feature_group_name)
        logger.info(f"FeatureGroup already exists: {fg.name}")
        result_name = fg.name
    except Exception:
        feature_group = feature_group_pb2.FeatureGroup(
            big_query=feature_group_pb2.FeatureGroup.BigQuery(
                big_query_source={"input_uri": f"bq://{bq_source_table}"},
                entity_id_columns=[entity_id_column],
            ),
            description=f"Auto-registered feature group: {feature_group_id}",
        )
        request = feature_registry_service.CreateFeatureGroupRequest(
            parent=parent,
            feature_group=feature_group,
            feature_group_id=feature_group_id,
        )
        operation = client.create_feature_group(request=request)
        result = operation.result()
        logger.info(f"Created FeatureGroup: {result.name}")
        result_name = result.name

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_uri_path, "w") as f:
        f.write(result_name)
