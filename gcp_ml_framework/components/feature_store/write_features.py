"""WriteFeatures — register a BQ table as a FeatureGroup (metadata only)."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class WriteFeatures(BaseComponent):
    """
    Register a BQ table as a Vertex AI Feature Store v2 FeatureGroup.

    This is a metadata-only operation — no data movement. The BQTransform
    upstream already wrote the data to BigQuery. WriteFeatures just tells
    the Feature Store "this BQ table is a feature source."

    Example:
        WriteFeatures(
            entity="user",
            feature_group="churn_signals",
            entity_id_column="user_id",
        )
    """

    entity: str
    feature_group: str
    entity_id_column: str = "entity_id"
    feature_time_column: str = "feature_timestamp"
    feature_ids: list[str] = field(default_factory=list)  # empty = all features in entity type
    bq_source_table: str | None = None  # defaults to the transform output_table
    component_name: str = "write_features"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self, base_image: str | None = None):
        from kfp import dsl  # type: ignore[import]

        image = base_image or "python:3.11-slim"
        pkgs = [] if base_image else ["google-cloud-aiplatform>=1.49"]

        @dsl.component(
            base_image=image,
            packages_to_install=pkgs,
        )
        def write_features(
            project: str,
            region: str,
            feature_group_id: str,
            bq_source_table: str,
            entity_id_column: str,
        ) -> str:
            """Register a BQ table as a FeatureGroup. Returns the FeatureGroup name."""
            from google.cloud import aiplatform

            aiplatform.init(project=project, location=region)

            from google.cloud.aiplatform_v1beta1 import (
                FeatureRegistryServiceClient,
            )
            from google.cloud.aiplatform_v1beta1.types import (
                feature_group as feature_group_pb2,
                feature_registry_service,
            )

            api_endpoint = f"{region}-aiplatform.googleapis.com"
            client = FeatureRegistryServiceClient(
                client_options={"api_endpoint": api_endpoint},
            )
            parent = f"projects/{project}/locations/{region}"
            feature_group_name = f"{parent}/featureGroups/{feature_group_id}"

            # Try to get existing FeatureGroup
            try:
                fg = client.get_feature_group(name=feature_group_name)
                print(f"FeatureGroup already exists: {fg.name}")
                return fg.name
            except Exception:
                pass

            # Create new FeatureGroup backed by BQ table
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
            print(f"Created FeatureGroup: {result.name}")
            return result.name

        return write_features

    def local_run(self, context: "MLContext", input_path: str = "", **kwargs: Any) -> str:
        """In local mode, log feature registration without touching Feature Store.

        Returns input_path unchanged — WriteFeatures is metadata-only and does not
        produce new data, so downstream steps should still see the upstream output.
        """
        import pandas as pd

        if input_path:
            df = pd.read_parquet(input_path)
            print(f"[local] WriteFeatures: {len(df)} rows for entity={self.entity!r}, "
                  f"feature_group={self.feature_group!r} (metadata registration only)")
        else:
            print(f"[local] WriteFeatures: registering entity={self.entity!r}, "
                  f"feature_group={self.feature_group!r} as FeatureGroup (no data movement)")
        return input_path


@dataclass
class ReadFeatures(BaseComponent):
    """
    Read feature values from the Vertex AI Feature Store for training or serving.

    For training: reads from the BQ source table (offline, point-in-time safe).
    For serving:  reads from the Bigtable online store (low-latency).
    """

    entity: str
    feature_group: str
    feature_ids: list[str] = field(default_factory=list)  # empty = all features
    output_table: str = "features_read"
    component_name: str = "read_features"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self, base_image: str | None = None):
        from kfp import dsl  # type: ignore[import]

        image = base_image or "python:3.11-slim"
        pkgs = [] if base_image else ["google-cloud-aiplatform[featurestore]>=1.49", "pyarrow>=15"]

        @dsl.component(
            base_image=image,
            packages_to_install=pkgs,
        )
        def read_features(
            project: str,
            region: str,
            dataset: str,
            entity: str,
            feature_group: str,
            feature_view_id: str,
            gcs_prefix: str,
            feature_ids: str,  # JSON list
        ) -> str:
            """Returns GCS URI of the exported feature Parquet."""
            import json

            from google.cloud import bigquery

            ids = json.loads(feature_ids)
            cols = ", ".join(ids) if ids else "*"
            client = bigquery.Client(project=project)
            table = f"{project}.{dataset}.feat_{entity}_{feature_group}"
            sql = f"SELECT entity_id, {cols} FROM `{table}`"
            df = client.query(sql).to_dataframe()
            # In KFP, we write to GCS via pandas
            import tempfile

            import pyarrow as pa
            import pyarrow.parquet as pq
            tmp = tempfile.mktemp(suffix=".parquet")
            pq.write_table(pa.Table.from_pandas(df), tmp)
            from google.cloud import storage
            sc = storage.Client(project=project)
            bucket_name = gcs_prefix[5:].split("/")[0]
            blob_path = "/".join(gcs_prefix[5:].split("/")[1:]) + f"features/{entity}_{feature_group}/features.parquet"
            sc.bucket(bucket_name).blob(blob_path).upload_from_filename(tmp)
            return f"gs://{bucket_name}/{blob_path}"

        return read_features

    def local_run(self, context: "MLContext", **kwargs: Any) -> str:
        """Read feature data from DuckDB (if connection provided) or return placeholder."""
        import os
        import tempfile

        import pandas as pd

        db_conn = kwargs.get("db_conn")
        dataset = context.bq_dataset
        table_name = f"feat_{self.entity}_{self.feature_group}"

        if db_conn is not None:
            # Try to read from DuckDB
            try:
                if self.feature_ids:
                    cols = ", ".join(self.feature_ids)
                    sql = f'SELECT {cols} FROM "{dataset}"."{table_name}"'
                else:
                    sql = f'SELECT * FROM "{dataset}"."{table_name}"'
                df = db_conn.sql(sql).df()
                print(f"[local] ReadFeatures: read {len(df)} rows from {dataset}.{table_name}")
            except Exception:
                print(f"[local] ReadFeatures: table {dataset}.{table_name} not found, using empty DataFrame")
                df = pd.DataFrame(columns=self.feature_ids or ["entity_id", "feature_placeholder"])
        else:
            df = pd.DataFrame(columns=self.feature_ids or ["entity_id", "feature_placeholder"])
            print(f"[local] ReadFeatures: no db_conn provided, returning empty DataFrame")

        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, f"{self.output_table}.parquet")
        df.to_parquet(out_path, index=False)
        return out_path
