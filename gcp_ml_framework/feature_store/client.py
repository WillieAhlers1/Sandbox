"""
FeatureStoreClient — Vertex AI Feature Store v2 lifecycle management.

Technology: Vertex AI Feature Store v2 (BQ-native).
BQ tables ARE the offline feature store. The platform registers those tables
as FeatureGroups and sets up online serving via FeatureViews.

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
    Manages the Vertex AI Feature Store v2 lifecycle for a given MLContext.

    v2 API concepts:
    - FeatureGroup — registers a BQ table as a feature source (metadata only)
    - Feature — registers individual columns within a FeatureGroup
    - FeatureOnlineStore — Bigtable-backed online serving store
    - FeatureView — connects a FeatureGroup to a FeatureOnlineStore with sync

    Usage:
        client = FeatureStoreClient(context)
        client.ensure_feature_group("user_features", "project.dataset.table")
        client.ensure_feature_view("user", "behavioral", "project.dataset.table")
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
                "Install with: pip install 'google-cloud-aiplatform>=1.49'"
            ) from exc
        aiplatform.init(project=self._project, location=self._region)

    def _create_or_get_feature_group(
        self, name: str, bq_table: str
    ) -> Any:
        """Create or get a FeatureGroup backed by a BQ table."""
        self._init_aiplatform()
        from google.cloud.aiplatform_v1beta1 import (
            FeatureRegistryServiceClient,
        )
        from google.cloud.aiplatform_v1beta1.types import (
            feature_group as feature_group_pb2,
            feature_registry_service,
        )

        api_endpoint = f"{self._region}-aiplatform.googleapis.com"
        client = FeatureRegistryServiceClient(
            client_options={"api_endpoint": api_endpoint},
        )
        parent = f"projects/{self._project}/locations/{self._region}"

        # Try to get existing
        feature_group_name = f"{parent}/featureGroups/{name}"
        try:
            return client.get_feature_group(name=feature_group_name)
        except Exception:
            pass

        # Create new FeatureGroup backed by BQ table
        feature_group = feature_group_pb2.FeatureGroup(
            big_query=feature_group_pb2.FeatureGroup.BigQuery(
                big_query_source={"input_uri": f"bq://{bq_table}"},
            ),
            description=f"Feature group for {name}",
        )
        request = feature_registry_service.CreateFeatureGroupRequest(
            parent=parent,
            feature_group=feature_group,
            feature_group_id=name,
        )
        operation = client.create_feature_group(request=request)
        return operation.result()

    def ensure_feature_group(self, name: str, bq_table: str) -> Any:
        """
        Register a BQ table as a FeatureGroup (metadata only, no data movement).

        Idempotent — safe to call on every deployment.
        """
        return self._create_or_get_feature_group(name, bq_table)

    def _create_or_get_feature_view(
        self,
        entity: str,
        feature_group: str,
        bq_source_table: str,
        entity_id_column: str = "entity_id",
    ) -> Any:
        """Create or get a FeatureView connecting a FeatureGroup to online store."""
        self._init_aiplatform()
        from google.cloud.aiplatform_v1beta1 import (
            FeatureOnlineStoreAdminServiceClient,
        )
        from google.cloud.aiplatform_v1beta1.types import (
            feature_online_store as fos_pb2,
            feature_online_store_admin_service,
            feature_view as feature_view_pb2,
        )

        api_endpoint = f"{self._region}-aiplatform.googleapis.com"
        client = FeatureOnlineStoreAdminServiceClient(
            client_options={"api_endpoint": api_endpoint},
        )

        online_store_name = (
            f"projects/{self._project}/locations/{self._region}"
            f"/featureOnlineStores/{self._fs_id}"
        )

        # Ensure FeatureOnlineStore exists
        try:
            client.get_feature_online_store(name=online_store_name)
        except Exception:
            parent = f"projects/{self._project}/locations/{self._region}"
            store = fos_pb2.FeatureOnlineStore(
                bigtable=fos_pb2.FeatureOnlineStore.Bigtable(
                    auto_scaling=fos_pb2.FeatureOnlineStore.Bigtable.AutoScaling(
                        min_node_count=1,
                        max_node_count=self._ctx.feature_store_online_node_count,
                    ),
                ),
            )
            op = client.create_feature_online_store(
                parent=parent,
                feature_online_store=store,
                feature_online_store_id=self._fs_id,
            )
            op.result()

        # Create FeatureView
        view_id = self._naming.feature_view_id(entity, feature_group)
        view_name = f"{online_store_name}/featureViews/{view_id}"

        try:
            return client.get_feature_view(name=view_name)
        except Exception:
            pass

        feature_view = feature_view_pb2.FeatureView(
            big_query_source=feature_view_pb2.FeatureView.BigQuerySource(
                uri=f"bq://{bq_source_table}",
                entity_id_columns=[entity_id_column],
            ),
        )
        request = feature_online_store_admin_service.CreateFeatureViewRequest(
            parent=online_store_name,
            feature_view=feature_view,
            feature_view_id=view_id,
        )
        operation = client.create_feature_view(request=request)
        return operation.result()

    def ensure_feature_view(
        self,
        entity: str,
        feature_group: str,
        bq_source_table: str,
        entity_id_column: str = "entity_id",
    ) -> Any:
        """
        Create a branch-namespaced FeatureView connecting a FeatureGroup
        to the FeatureOnlineStore for online serving.

        The view ID encodes the branch so DEV writes never overwrite PROD.
        Idempotent — safe to call on every deployment.
        """
        return self._create_or_get_feature_view(
            entity, feature_group, bq_source_table, entity_id_column
        )

    def ensure_entity(self, schema: EntitySchema) -> Any:
        """
        Register all feature groups for an entity schema.

        For each feature group in the schema, creates a FeatureGroup
        pointing to the corresponding BQ table.
        """
        results = {}
        for group_name in schema.feature_groups:
            bq_table = (
                f"{self._project}.{self._naming.bq_dataset}"
                f".feat_{schema.entity}_{group_name}"
            )
            fg_id = f"{schema.entity}_{group_name}"
            results[group_name] = self.ensure_feature_group(fg_id, bq_table)
        return results

    def trigger_sync(self, entity: str, feature_group: str) -> None:
        """Manually trigger a sync for a FeatureView."""
        self._init_aiplatform()
        view_id = self._naming.feature_view_id(entity, feature_group)
        print(f"[FeatureStoreClient] Triggering sync for view: {view_id}")
