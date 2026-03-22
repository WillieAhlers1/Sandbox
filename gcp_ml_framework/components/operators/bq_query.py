"""BQQuery — BigQuery SQL query as a unified component.

Absorbs BQQueryTask logic into the component system. Marked as @task so the
SmartCompiler renders it as a native Airflow BigQueryInsertJobOperator.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import model_validator

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


def _resolve_templates(text: str, context: MLContext) -> str:
    """Replace framework template vars. Convert {run_date} to Airflow macro."""
    result = text.replace("{bq_dataset}", context.bq_dataset)
    result = result.replace("{gcs_prefix}", context.gcs_prefix)
    result = result.replace("{namespace}", context.namespace)
    result = result.replace("{run_date}", "{{ ds }}")
    return result


@task
class BQQuery(BaseComponent):
    """Execute a BigQuery SQL query.

    Template variables in sql:
      {bq_dataset}  — branch-namespaced BQ dataset
      {gcs_prefix}  — branch GCS path
      {namespace}   — branch namespace
      {run_date}    — converted to Airflow {{ ds }} macro at runtime

    Either ``sql`` (inline) or ``sql_file`` (path to .sql file) must be provided.
    """

    sql: str = ""
    sql_file: str | None = None
    destination_table: str | None = None
    write_disposition: str = "WRITE_TRUNCATE"
    create_disposition: str = "CREATE_IF_NEEDED"
    component_name: str = "bq_query"

    @model_validator(mode="after")
    def _check_sql_source(self) -> BQQuery:
        if self.sql and self.sql_file:
            raise ValueError("BQQuery: sql and sql_file are mutually exclusive")
        if not self.sql and not self.sql_file:
            raise ValueError("BQQuery requires either sql or sql_file")
        return self

    def _load_sql(self, pipeline_dir: Path | None = None) -> str:
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
        raw = self._load_sql(pipeline_dir)
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

    def execute(self) -> None:
        """Execute query via BigQuery Python SDK (for local execution)."""
        from google.cloud import bigquery

        client = bigquery.Client(project=self.project)
        sql = self._load_sql()
        sql = sql.format(
            bq_dataset=self.dataset,
            gcs_prefix=getattr(self, "gcs_prefix", ""),
            namespace=getattr(self, "namespace", ""),
            run_date=self.run_date,
        )
        job_config = bigquery.QueryJobConfig(
            write_disposition=self.write_disposition,
        )
        if self.destination_table:
            job_config.destination = (
                f"{self.project}.{self.dataset}.{self.destination_table}"
            )
            job_config.create_disposition = self.create_disposition
        job = client.query(sql, job_config=job_config)
        job.result()  # block until done

        # Write output reference for cross-step data flow
        if self.output_uri_path and self.destination_table:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(
                f"{self.project}.{self.dataset}.{self.destination_table}"
            )

    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation.

        Used by SmartCompiler to render this component as a native Airflow operator.
        """
        imports = {
            "from airflow.providers.google.cloud.operators.bigquery"
            " import BigQueryInsertJobOperator",
        }

        resolved_sql = self.resolve_sql(context, pipeline_dir)
        escaped_sql = resolved_sql.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")

        dest = self.resolve_destination(context)
        query_config = f"""{{
        "query": '''{escaped_sql}''',
        "useLegacySql": False,"""

        if dest is not None:
            query_config += f"""
        "destinationTable": {dest!r},
        "writeDisposition": "{self.write_disposition}",
        "createDisposition": "{self.create_disposition}","""

        query_config += "\n    }"

        code = f"""BigQueryInsertJobOperator(
        task_id="{{{{ task_id }}}}",
        configuration={{"query": {query_config}}},
        gcp_conn_id="google_cloud_default",
    )"""

        return code, imports
