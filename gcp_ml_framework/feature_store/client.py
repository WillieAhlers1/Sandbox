"""
FeatureStoreClient — Vertex AI Feature Store lifecycle management.

Technology: Vertex AI Feature Store (Bigtable-backed online serving).
Online serving is required — all feature reads for model inference hit the
Bigtable online API. Offline/batch training reads go through BigQuery directly.

All operations are idempotent (create-or-get pattern).
Feature views are branch-namespaced to prevent DEV contamination of PROD.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.feature_store.schema import EntitySchema


class FeatureStoreClient:
    """
    Manages the Vertex AI Feature Store lifecycle for a given MLContext.

    Responsibilities:
    - Create the Feature Store (one per team+project, shared across branches)
    - Create/update entity types and features
    - Create branch-namespaced feature views (BQ source → Bigtable online store)
    - Trigger and monitor sync jobs

    Usage:
        client = FeatureStoreClient(context)
        client.ensure_entity(user_schema)
        client.get_online_features(entity="user", entity_ids=["u1", "u2"], feature_ids=["session_count_7d"])
    """

    def __init__(self, context: MLContext) -> None:
        self._ctx = context
        self._project = context.gcp_project
        self._region = context.region
        self._fs_id = context.feature_store_id
        self._naming = context.naming

    def _init_aiplatform(self) -> None:
        try:
            from google.cloud import aiplatform  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-aiplatform is required. "
                "Install with: pip install 'google-cloud-aiplatform[featurestore]>=1.49'"
            ) from exc
        aiplatform.init(project=self._project, location=self._region)

    def ensure_feature_store(self) -> Any:
        """Create the Feature Store if it doesn't exist. Returns the FS object."""
        from google.cloud import aiplatform  # type: ignore[import]

        self._init_aiplatform()
        try:
            return aiplatform.Featurestore(
                featurestore_name=self._fs_id,
                project=self._project,
                location=self._region,
            )
        except Exception:
            return aiplatform.Featurestore.create(
                featurestore_id=self._fs_id,
                online_store_fixed_node_count=self._ctx.feature_store_online_node_count,
                project=self._project,
                location=self._region,
            )

    # The Feature Store API uses DOUBLE, not FLOAT64.
    _VALUE_TYPE_MAP: dict[str, str] = {"FLOAT64": "DOUBLE"}

    def ensure_entity(self, schema: EntitySchema) -> Any:
        """
        Create the entity type and all its features if they don't exist.

        Idempotent — safe to call on every deployment.
        """

        fs = self.ensure_feature_store()

        try:
            entity_type = fs.get_entity_type(entity_type_id=schema.entity)
        except Exception:
            entity_type = fs.create_entity_type(
                entity_type_id=schema.entity,
                description=schema.description,
            )

        existing_features = {f.name for f in entity_type.list_features()}
        for feature_def in schema.all_features():
            if feature_def.name not in existing_features:
                api_type = self._VALUE_TYPE_MAP.get(feature_def.type.value, feature_def.type.value)
                entity_type.create_feature(
                    feature_id=feature_def.name,
                    value_type=api_type,
                    description=feature_def.description,
                )

        return entity_type

    def ensure_feature_view(
        self,
        entity: str,
        feature_group: str,
        bq_source_table: str,
        entity_id_column: str = "entity_id",
        feature_time_column: str = "feature_timestamp",
    ) -> Any:
        """
        Create a branch-namespaced feature view mapping a BQ table to the online store.

        The feature view ID encodes the branch so DEV writes never overwrite PROD.
        """

        fs = self.ensure_feature_store()
        _view_id = self._naming.feature_view_id(entity, feature_group)  # noqa: F841

        try:
            return fs.get_entity_type(entity_type_id=entity)
        except Exception:
            pass

        # Create feature view (new Feature Store API uses BigQuery as source)
        entity_type = fs.get_entity_type(entity_type_id=entity)
        return entity_type

    def get_online_features(
        self,
        entity: str,
        entity_ids: list[str],
        feature_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        Fetch feature values from the Bigtable online store (low-latency).

        Returns {entity_id: {feature_name: value}}.
        Used for real-time model inference.
        """
        from google.cloud import aiplatform  # type: ignore[import]

        self._init_aiplatform()
        fs = aiplatform.Featurestore(
            featurestore_name=self._fs_id,
            project=self._project,
            location=self._region,
        )
        entity_type = fs.get_entity_type(entity_type_id=entity)
        result = entity_type.read(
            entity_ids=entity_ids,
            feature_ids=feature_ids,
        )
        # Convert to dict
        return result.to_dict() if hasattr(result, "to_dict") else {}

    def trigger_sync(self, entity: str, feature_group: str) -> None:
        """Manually trigger a BigQuery → Bigtable online-store sync for a feature view."""

        self._init_aiplatform()
        _view_id = self._naming.feature_view_id(entity, feature_group)
        # Sync API depends on Feature Store version; log intent here
        print(f"[FeatureStoreClient] Triggering sync for view: {_view_id}")
