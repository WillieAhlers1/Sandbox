"""BQQueryTask — execute a BigQuery SQL query as a Composer task."""

from __future__ import annotations

from dataclasses import dataclass, field
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
      {run_date}    — converted to Airflow {{ ds }} macro
    """

    task_type: str = field(default="bq_query", init=False)
    config: TaskConfig = field(default_factory=TaskConfig)

    sql: str = ""
    destination_table: str | None = None
    write_disposition: str = "WRITE_TRUNCATE"
    create_disposition: str = "CREATE_IF_NEEDED"

    def resolve_sql(self, context: MLContext) -> str:
        """Resolve framework template variables in SQL."""
        return _resolve_templates(self.sql, context)

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
        if not self.sql.strip():
            errors.append("BQQueryTask requires non-empty sql")
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
