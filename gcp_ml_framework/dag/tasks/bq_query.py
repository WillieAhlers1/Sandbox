"""BQQueryTask — execute a BigQuery SQL query as a Composer task."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


def _resolve_templates(text: str, context: MLContext) -> str:
    """Replace framework template vars. Convert {run_date} to Airflow macro."""
    result = text.replace("{bq_dataset}", context.bq_dataset)
    result = result.replace("{gcs_prefix}", context.gcs_prefix)
    result = result.replace("{namespace}", context.namespace)
    result = result.replace("{run_date}", "{{ ds }}")
    return result


@dataclass
class BQQueryTask(BaseTask):
    """
    Execute a BigQuery SQL query as a Composer task.

    Template variables in sql:
      {bq_dataset}  — branch-namespaced BQ dataset
      {gcs_prefix}  — branch GCS path
      {namespace}   — branch namespace
      {run_date}    — converted to Airflow {{ ds }} macro

    Either `sql` (inline) or `sql_file` (path to .sql file) must be provided.
    They are mutually exclusive.
    """

    task_type: str = field(default="bq_query", init=False)
    config: TaskConfig = field(default_factory=TaskConfig)

    sql: str = ""
    sql_file: str | None = None
    destination_table: str | None = None
    write_disposition: str = "WRITE_TRUNCATE"
    create_disposition: str = "CREATE_IF_NEEDED"

    def _load_sql_content(self, pipeline_dir: Path | None = None) -> str:
        """Load SQL content from sql_file or return inline sql."""
        if self.sql:
            return self.sql
        if self.sql_file:
            path = Path(self.sql_file)
            if not path.is_absolute() and pipeline_dir:
                path = pipeline_dir / path
            if not path.exists():
                raise FileNotFoundError(f"SQL file not found: {path}")
            return path.read_text()
        return ""

    def resolve_sql(self, context: MLContext, pipeline_dir: Path | None = None) -> str:
        """Resolve framework template variables in SQL."""
        raw = self._load_sql_content(pipeline_dir)
        return _resolve_templates(raw, context)

    def resolve_destination(self, context: MLContext) -> dict[str, str] | None:
        """Return BQ destination table dict, or None if no destination."""
        if self.destination_table is None:
            return None
        return {
            "projectId": context.gcp_project,
            "datasetId": context.bq_dataset,
            "tableId": self.destination_table,
        }

    def validate(self, context: MLContext) -> list[str]:
        errors: list[str] = []
        if self.sql and self.sql_file:
            errors.append("BQQueryTask: sql and sql_file are mutually exclusive — specify only one")
        if not self.sql and not self.sql_file:
            errors.append("BQQueryTask requires either sql or sql_file")
        return errors

    def as_airflow_operator(self, context: MLContext, dag: Any, task_id: str) -> Any:
        from airflow.providers.google.cloud.operators.bigquery import (  # type: ignore[import]
            BigQueryInsertJobOperator,
        )

        query_config: dict[str, Any] = {
            "query": self.resolve_sql(context),
            "useLegacySql": False,
        }
        dest = self.resolve_destination(context)
        if dest is not None:
            query_config["destinationTable"] = dest
            query_config["writeDisposition"] = self.write_disposition
            query_config["createDisposition"] = self.create_disposition

        return BigQueryInsertJobOperator(
            task_id=task_id,
            configuration={"query": query_config},
            gcp_conn_id="google_cloud_default",
            dag=dag,
        )
