"""BigQueryExtract — run a SQL query and export results to GCS as Parquet."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class BigQueryExtract(BaseComponent):
    """
    Execute a BigQuery SQL query and write results to GCS as Parquet.

    Template variables available in `query`:
        {bq_dataset}  — the branch-namespaced BQ dataset
        {gcs_prefix}  — the branch-namespaced GCS prefix
        {run_date}    — the Airflow execution date (YYYY-MM-DD)

    Example:
        BigQueryExtract(
            query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
            output_table="raw_events_extract",
        )
    """

    query: str
    output_table: str
    write_disposition: str = "WRITE_TRUNCATE"
    component_name: str = "bigquery_extract"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=[
                "google-cloud-bigquery>=3.17",
                "google-cloud-storage>=2.16",
                "pyarrow>=15",
            ],
        )
        def bigquery_extract(
            project: str,
            dataset: str,
            query: str,
            output_table: str,
            gcs_prefix: str,
            write_disposition: str,
        ) -> str:
            """Returns the GCS URI of the exported Parquet files."""
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
            full_table = f"{project}.{dataset}.{output_table}"
            job_config = bigquery.QueryJobConfig(
                destination=full_table,
                write_disposition=write_disposition,
            )
            rendered_query = query.format(bq_dataset=dataset, gcs_prefix=gcs_prefix)
            client.query(rendered_query, job_config=job_config).result()

            output_uri = f"{gcs_prefix}extracts/{output_table}/*.parquet"
            extract_cfg = bigquery.ExtractJobConfig(destination_format="PARQUET")
            client.extract_table(full_table, output_uri, job_config=extract_cfg).result()
            return output_uri

        return bigquery_extract

    def local_run(self, context: "MLContext", run_date: str = "", **kwargs: Any) -> str:
        """Run the BQ query locally using DuckDB and write Parquet to a temp dir."""
        import duckdb
        import tempfile
        import os

        rendered = self.query.format(
            bq_dataset=context.bq_dataset,
            gcs_prefix=context.gcs_prefix,
            run_date=run_date or "2024-01-01",
        )
        # DuckDB uses ANSI double-quote identifier quoting; BigQuery uses backticks.
        rendered = rendered.replace("`", '"')
        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, "output.parquet")
        duckdb.sql(f"COPY ({rendered}) TO '{out_path}' (FORMAT PARQUET)")
        return out_path
