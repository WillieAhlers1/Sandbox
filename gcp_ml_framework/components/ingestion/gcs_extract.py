"""GCSExtract — copy files from a GCS source path to the branch staging prefix."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class GCSExtract(BaseComponent):
    """
    Copy one or more files from a GCS source URI into the branch staging prefix.

    Example:
        GCSExtract(
            source_uri="gs://data-lake/raw/events/*.parquet",
            destination_folder="raw_events",
        )
    """

    source_uri: str
    destination_folder: str
    component_name: str = "gcs_extract"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-storage>=2.16"],
        )
        def gcs_extract(
            source_uri: str,
            gcs_prefix: str,
            destination_folder: str,
            project: str,
        ) -> str:
            from google.cloud import storage
            import fnmatch

            client = storage.Client(project=project)
            dest_prefix = f"{gcs_prefix}staging/{destination_folder}/"

            # Parse bucket and blob prefix from source_uri
            without_scheme = source_uri[5:]  # strip "gs://"
            src_bucket_name, _, src_path = without_scheme.partition("/")
            src_bucket = client.bucket(src_bucket_name)

            pattern = src_path if "*" in src_path else src_path + "/*"
            blobs = list(client.list_blobs(src_bucket_name, prefix=src_path.split("*")[0]))

            dest_bucket_name = gcs_prefix[5:].split("/")[0]
            dest_bucket = client.bucket(dest_bucket_name)
            dest_prefix_path = "/".join(gcs_prefix[5:].split("/")[1:]) + f"staging/{destination_folder}/"

            for blob in blobs:
                if fnmatch.fnmatch(blob.name, pattern.replace(src_path.split("*")[0], "")):
                    dest_blob_name = dest_prefix_path + blob.name.split("/")[-1]
                    src_bucket.copy_blob(blob, dest_bucket, dest_blob_name)

            return dest_prefix

        return gcs_extract

    def local_run(self, context: "MLContext", **kwargs: Any) -> str:
        import shutil
        import tempfile

        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.destination_folder}_")
        # In local mode, create an empty placeholder directory
        return out_dir
