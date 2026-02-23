"""BQTransform — run a SQL transformation in BigQuery and write to a BQ table."""

from __future__ import annotations

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

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-bigquery>=3.17"],
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
        import duckdb
        import tempfile
        import os

        sql = self._get_sql()
        rendered = sql.format(
            bq_dataset=context.bq_dataset,
            gcs_prefix=context.gcs_prefix,
            run_date=run_date or "2024-01-01",
        )
        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, f"{self.output_table}.parquet")
        duckdb.sql(f"COPY ({rendered}) TO '{out_path}' (FORMAT PARQUET)")
        return out_path


@dataclass
class PandasTransform(BaseComponent):
    """
    Apply a Python function transformation (local only, used by LocalRunner stubs).

    Not submitted to Vertex AI — maps to a BQTransform for production runs.
    Useful for rapid local iteration where you don't need BigQuery.
    """

    transform_fn: Any  # callable(df: pd.DataFrame, ctx: MLContext) -> pd.DataFrame
    output_table: str
    input_table: str = ""
    component_name: str = "pandas_transform"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self):
        raise NotImplementedError(
            "PandasTransform is a local-only stub. Use BQTransform for production."
        )

    def local_run(self, context: "MLContext", input_path: str = "", **kwargs: Any) -> str:
        import pandas as pd
        import tempfile
        import os

        df = pd.read_parquet(input_path) if input_path else pd.DataFrame()
        result = self.transform_fn(df, context)
        out_dir = tempfile.mkdtemp(prefix=f"gml_{self.output_table}_")
        out_path = os.path.join(out_dir, f"{self.output_table}.parquet")
        result.to_parquet(out_path, index=False)
        return out_path
