"""BigQueryExtract — run a SQL query and export results to GCS as Parquet."""

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task


@task
class BigQueryExtract(BaseComponent):
    """
    Execute a BigQuery SQL query and write results to GCS as Parquet.

    Template variables available in `query`:
        {bq_dataset}  — the branch-namespaced BQ dataset
        {gcs_prefix}  — the branch-namespaced GCS prefix
        {run_date}    — the Airflow execution date (YYYY-MM-DD)

    Example:
        BigQueryExtract(
            component_name="ingest",
            query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
            output_table="raw_events_extract",
        )
    """

    # Component-specific fields
    dataset: str = ""
    gcs_prefix: str = ""

    query: str
    output_table: str
    write_disposition: str = "WRITE_TRUNCATE"
    component_name: str = "bigquery_extract"

    def execute(self) -> None:
        """Container lifecycle: delegate to utils.bigquery_extract.run_bigquery_extract()."""
        from gcp_ml_framework.utils.bigquery_extract import run_bigquery_extract

        run_bigquery_extract(
            project=self.project,
            dataset=self.dataset,
            query=self.query,
            output_table=self.output_table,
            gcs_prefix=self.gcs_prefix,
            write_disposition=self.write_disposition,
            run_date=self.run_date,
            output_uri_path=self.output_uri_path,
        )



if __name__ == "__main__":
    BigQueryExtract.cli()
