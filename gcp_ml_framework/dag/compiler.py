"""
DAGCompiler — compiles a DAGDefinition to an Airflow DAG Python file.

The generated file is self-contained: it imports Airflow operators directly,
resolves framework template variables at compile time, and preserves Airflow
Jinja macros ({{ ds }}) for runtime resolution.

Generated DAGs have ZERO gcp_ml_framework imports.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.dag.builder import DAGDefinition

from gcp_ml_framework.config import GitState
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask


class DAGCompiler:
    """Compiles a DAGDefinition to an Airflow-compatible Python file."""

    def __init__(self, output_dir: Path | str = "dags", pipeline_dir: Path | None = None) -> None:
        self.output_dir = Path(output_dir)
        self._pipeline_dir = Path(pipeline_dir) if pipeline_dir else None

    def compile(self, dag_def: DAGDefinition, context: MLContext) -> Path:
        """Compile the DAG to an Airflow Python file. Returns the file path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        dag_id = context.naming.dag_id(dag_def.name)
        output_path = self.output_dir / f"{dag_id}.py"
        output_path.write_text(self.render(dag_def, context))
        return output_path

    def render(self, dag_def: DAGDefinition, context: MLContext) -> str:
        """Render the Python source of the Airflow DAG file."""
        dag_id = context.naming.dag_id(dag_def.name)
        description = dag_def.description or f"GML DAG: {dag_def.name}"

        # DEV: disable automatic scheduling to prevent backfill runs.
        # Data scientists trigger manually via `gml run --composer`.
        # STAGING/PROD: use the declared schedule for production cadence.
        if context.git_state == GitState.DEV:
            schedule = "None"
        else:
            schedule = repr(dag_def.schedule)

        tags = (
            [context.naming.team, context.naming.project, context.naming.branch]
            + dag_def.tags
        )

        # Collect which imports are needed
        imports = set()
        task_blocks = []
        for dag_task in dag_def.tasks:
            block, task_imports = self._render_task(dag_task, context)
            task_blocks.append(block)
            imports.update(task_imports)

        dep_lines = self._render_dependencies(dag_def)

        imports_str = "\n".join(sorted(imports))
        tasks_str = "\n\n".join(task_blocks)
        deps_str = "\n    ".join(dep_lines) if dep_lines else ""

        return f'''\
"""
Auto-generated Airflow DAG: {dag_def.name}
Namespace: {context.namespace}
GCP project: {context.gcp_project}

DO NOT EDIT MANUALLY.
Regenerate with: gml compile
"""
from datetime import datetime, timedelta

from airflow import DAG
{imports_str}

_default_args = {{
    "owner": "gcp-mlf",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
}}

with DAG(
    dag_id="{dag_id}",
    description="{description}",
    schedule={schedule},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags={tags!r},
    default_args=_default_args,
) as dag:

{textwrap.indent(tasks_str, "    ")}

    # --- Dependencies ---
    {deps_str}
'''

    def _render_task(
        self, dag_task, context: MLContext
    ) -> tuple[str, set[str]]:
        """Render a single task block. Returns (code, imports)."""
        task = dag_task.task
        name = dag_task.name

        if isinstance(task, BQQueryTask):
            return self._render_bq_query(name, task, context)
        if isinstance(task, EmailTask):
            return self._render_email(name, task, context)
        if isinstance(task, VertexPipelineTask):
            return self._render_vertex_pipeline(name, task, context)

        raise TypeError(f"Unknown task type: {type(task).__name__}")

    def _render_bq_query(
        self, name: str, task: BQQueryTask, context: MLContext
    ) -> tuple[str, set[str]]:
        imports = {
            "from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator",
        }
        resolved_sql = task.resolve_sql(context, pipeline_dir=self._pipeline_dir)
        # Escape backslashes and triple-quote-breaking sequences
        sql_escaped = resolved_sql.replace("\\", "\\\\")

        dest = task.resolve_destination(context)
        dest_block = ""
        if dest is not None:
            dest_block = f"""
            "destinationTable": {{
                "projectId": "{dest['projectId']}",
                "datasetId": "{dest['datasetId']}",
                "tableId": "{dest['tableId']}",
            }},
            "writeDisposition": "{task.write_disposition}",
            "createDisposition": "{task.create_disposition}","""

        code = f'''{name} = BigQueryInsertJobOperator(
    task_id="{name}",
    configuration={{
        "query": {{
            "query": """{sql_escaped}""",
            "useLegacySql": False,{dest_block}
        }}
    }},
    gcp_conn_id="google_cloud_default",
)'''
        return code, imports

    def _render_email(
        self, name: str, task: EmailTask, context: MLContext
    ) -> tuple[str, set[str]]:
        imports = {"from airflow.operators.email import EmailOperator"}
        subject = task.resolve_subject(context)
        body = task.resolve_body(context)
        to_repr = repr(task.to)
        # Escape backslashes
        subject_escaped = subject.replace("\\", "\\\\")
        body_escaped = body.replace("\\", "\\\\")

        code = f'''{name} = EmailOperator(
    task_id="{name}",
    to={to_repr},
    subject="""{subject_escaped}""",
    html_content="""{body_escaped}""",
)'''
        return code, imports

    def _render_vertex_pipeline(
        self, name: str, task: VertexPipelineTask, context: MLContext
    ) -> tuple[str, set[str]]:
        """Generate a self-contained CreatePipelineJobOperator.

        The generated code references a pre-compiled KFP YAML at its GCS path.
        No gcp_ml_framework imports are needed at Airflow parse time.
        """
        imports = {
            "from airflow.providers.google.cloud.operators.vertex_ai.pipeline_job import CreatePipelineJobOperator",
        }

        pipeline_name = task.pipeline_name
        template_path = (
            f"gs://{context.naming.gcs_bucket}/{context.naming.branch}"
            f"/pipelines/{pipeline_name}/pipeline.yaml"
        )
        pipeline_root = (
            f"gs://{context.naming.gcs_bucket}/{context.naming.branch}"
            f"/pipeline_runs/{pipeline_name}/"
        )

        code = f"""{name} = CreatePipelineJobOperator(
    task_id="{name}",
    project_id="{context.gcp_project}",
    region="{context.region}",
    display_name="{pipeline_name}_{{{{{{ ds_nodash }}}}}}",
    template_path="{template_path}",
    pipeline_root="{pipeline_root}",
    enable_caching={task.enable_caching!r},
)"""
        return code, imports

    def _render_dependencies(self, dag_def: DAGDefinition) -> list[str]:
        """Generate Airflow >> dependency lines."""
        lines: list[str] = []
        for task in dag_def.tasks:
            if not task.depends_on:
                continue
            if len(task.depends_on) == 1:
                lines.append(f"{task.depends_on[0]} >> {task.name}")
            else:
                deps = ", ".join(task.depends_on)
                lines.append(f"[{deps}] >> {task.name}")
        return lines
