"""BQTransform — run a SQL transformation in BigQuery and write to a BQ table."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class BQTransform(BaseComponent):
    """
    Execute a SQL file as a BigQuery job and materialise results to a table.

    Either `sql_file` (path to a .sql file relative to the pipeline dir) or
    `sql` (inline SQL string) must be provided.

    Template variables available in SQL:
        {bq_dataset}  — branch-namespaced BQ dataset
        {gcs_prefix}  — branch GCS prefix
        {run_date}    — Airflow execution date

    Example:
        BQTransform(
            sql_file="sql/churn_features.sql",
            output_table="churn_features",
        )
    """

    output_table: str
    sql_file: str | None = None
    sql: str | None = None
    write_disposition: str = "WRITE_TRUNCATE"
    component_name: str = "bq_transform"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def __post_init__(self) -> None:
        if not self.sql_file and not self.sql:
            raise ValueError("BQTransform requires either sql_file or sql")

    def _get_sql(self) -> str:
        if self.sql:
            return self.sql
        path = Path(self.sql_file)  # type: ignore[arg-type]
        if not path.exists():
            raise FileNotFoundError(f"SQL file not found: {path}")
        return path.read_text()

    def as_kfp_component(self, base_image: str | None = None):
        from kfp import dsl  # type: ignore[import]

        image = base_image or "python:3.11-slim"
        pkgs = [] if base_image else ["google-cloud-bigquery>=3.17"]

        @dsl.component(
            base_image=image,
            packages_to_install=pkgs,
        )
        def bq_transform(
            project: str,
            dataset: str,
            sql: str,
            output_table: str,
            write_disposition: str,
            run_date: str = "",
        ) -> str:
            """Returns the fully-qualified output table name."""
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
            rendered = sql.format(
                bq_dataset=dataset,
                run_date=run_date,
            )
            dest = f"{project}.{dataset}.{output_table}"
            cfg = bigquery.QueryJobConfig(
                destination=dest,
                write_disposition=write_disposition,
                use_legacy_sql=False,
            )
            client.query(rendered, job_config=cfg).result()
            return dest

        return bq_transform

    def local_run(self, context: "MLContext", run_date: str = "", **kwargs: Any) -> str:
        import os
        import tempfile

        import duckdb

        # Use the shared connection from LocalRunner so intermediate tables are visible.
        # Fall back to a fresh connection when called outside the runner (e.g. tests).
        conn: duckdb.DuckDBPyConnection = kwargs.get("db_conn") or duckdb.connect()

        sql = self._get_sql()
        rendered = sql.format(
            bq_dataset=context.bq_dataset,
            gcs_prefix=context.gcs_prefix,
            run_date=run_date or "2024-01-01",
        )
        # Translate BigQuery SQL idioms to DuckDB-compatible equivalents.
        from gcp_ml_framework.utils.sql_compat import bq_to_duckdb
        rendered = bq_to_duckdb(rendered)
        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, f"{self.output_table}.parquet")
        conn.sql(f"COPY ({rendered}) TO '{out_path}' (FORMAT PARQUET)")
        return out_path
