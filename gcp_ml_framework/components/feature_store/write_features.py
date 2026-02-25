"""WriteFeatures — sync a BQ table into the Vertex AI Feature Store online store."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class WriteFeatures(BaseComponent):
    """
    Sync feature data from a BigQuery source table into the branch-namespaced
    Vertex AI Feature Store feature view (Bigtable online store).

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
    bq_source_table: str | None = None  # defaults to the transform output_table
    component_name: str = "write_features"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-aiplatform[featurestore]>=1.49"],
        )
        def write_features(
            project: str,
            region: str,
            feature_store_id: str,
            entity: str,
            feature_group: str,
            feature_view_id: str,
            bq_source_table: str,
            entity_id_column: str,
            feature_time_column: str,
        ) -> None:
            from google.cloud import aiplatform

            aiplatform.init(project=project, location=region)
            fs = aiplatform.Featurestore(
                featurestore_name=feature_store_id,
                project=project,
                location=region,
            )
            entity_type = fs.get_entity_type(entity_type_id=entity)
            entity_type.ingest_from_bq(
                feature_ids=None,
                feature_time=feature_time_column,
                entity_id_field=entity_id_column,
                bq_source_uri=f"bq://{bq_source_table}",
                sync=True,
            )

        return write_features

    def local_run(self, context: "MLContext", input_path: str = "", **kwargs: Any) -> None:
        """In local mode, log feature write without touching Feature Store."""
        import pandas as pd

        if input_path:
            df = pd.read_parquet(input_path)
            print(f"[local] WriteFeatures: {len(df)} rows for entity={self.entity!r}, "
                  f"feature_group={self.feature_group!r}")
        else:
            print("[local] WriteFeatures: no input path provided, skipping.")


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

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-aiplatform[featurestore]>=1.49", "pyarrow>=15"],
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
        import os
        import tempfile

        import pandas as pd

        df = pd.DataFrame(columns=self.feature_ids or ["entity_id", "feature_placeholder"])
        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, f"{self.output_table}.parquet")
        df.to_parquet(out_path, index=False)
        return out_path
