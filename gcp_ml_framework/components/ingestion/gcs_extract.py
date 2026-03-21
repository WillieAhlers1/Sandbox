"""GCSExtract — copy files from a GCS source path to the branch staging prefix."""

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task


@task
class GCSExtract(BaseComponent):
    """
    Copy one or more files from a GCS source URI into the branch staging prefix.

    Example:
        GCSExtract(
            component_name="gcs_extract",
            source_uri="gs://data-lake/raw/events/*.parquet",
            destination_folder="raw_events",
        )
    """

    # Component-specific fields
    gcs_prefix: str = ""

    source_uri: str
    destination_folder: str
    component_name: str = "gcs_extract"

    def execute(self) -> None:
        """Container lifecycle: delegate to utils.gcs_extract.run_gcs_extract()."""
        from gcp_ml_framework.utils.gcs_extract import run_gcs_extract

        run_gcs_extract(
            source_uri=self.source_uri,
            gcs_prefix=self.gcs_prefix,
            destination_folder=self.destination_folder,
            project=self.project,
            output_uri_path=self.output_uri_path,
        )



if __name__ == "__main__":
    GCSExtract.cli()
