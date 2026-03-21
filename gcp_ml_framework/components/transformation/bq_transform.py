"""BQTransform — run a SQL transformation in BigQuery and write to a BQ table."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import model_validator

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@task
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
            component_name="transform",
            sql_file="sql/churn_features.sql",
            output_table="churn_features",
        )
    """

    # Component-specific fields
    dataset: str = ""

    output_table: str
    sql_file: str | None = None
    sql: str | None = None
    write_disposition: str = "WRITE_TRUNCATE"
    component_name: str = "bq_transform"

    @model_validator(mode="after")
    def _check_sql_source(self) -> BQTransform:
        if not self.sql_file and not self.sql:
            raise ValueError("BQTransform requires either sql_file or sql")
        return self

    def _get_sql(self) -> str:
        if self.sql:
            return self.sql
        path = Path(self.sql_file)  # type: ignore[arg-type]
        if not path.exists():
            raise FileNotFoundError(f"SQL file not found: {path}")
        return path.read_text()

    def execute(self) -> None:
        """Container lifecycle: delegate to utils.bq_transform.run_bq_transform()."""
        from gcp_ml_framework.utils.bq_transform import run_bq_transform

        sql = self.sql or self._get_sql()
        run_bq_transform(
            project=self.project,
            dataset=self.dataset,
            sql=sql,
            output_table=self.output_table,
            write_disposition=self.write_disposition,
            run_date=self.run_date,
            output_uri_path=self.output_uri_path,
        )

    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation."""
        from gcp_ml_framework.components.operators.bq_query import _resolve_templates

        imports = {
            "from airflow.providers.google.cloud.operators.bigquery"
            " import BigQueryInsertJobOperator",
        }

        sql = self._get_sql()
        resolved_sql = _resolve_templates(sql, context)
        escaped_sql = resolved_sql.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")

        dest = {
            "projectId": context.gcp_project,
            "datasetId": context.bq_dataset,
            "tableId": self.output_table,
        }

        code = f"""BigQueryInsertJobOperator(
        task_id="{{{{ task_id }}}}",
        configuration={{"query": {{
            "query": '''{escaped_sql}''',
            "useLegacySql": False,
            "destinationTable": {dest!r},
            "writeDisposition": "{self.write_disposition}",
            "createDisposition": "CREATE_IF_NEEDED",
        }}}},
        gcp_conn_id="google_cloud_default",
    )"""

        return code, imports


if __name__ == "__main__":
    BQTransform.cli()
