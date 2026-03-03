"""
DAGCompiler — compiles a DAGDefinition to an Airflow DAG Python file.

The generated file is self-contained: it imports Airflow operators directly,
resolves framework template variables at compile time, and preserves Airflow
Jinja macros ({{ ds }}) for runtime resolution.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.dag.builder import DAGDefinition

from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask


class DAGCompiler:
    """Compiles a DAGDefinition to an Airflow-compatible Python file."""

    def __init__(self, output_dir: Path | str = "dags") -> None:
        self.output_dir = Path(output_dir)

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
Regenerate with: gml deploy dags
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
        resolved_sql = task.resolve_sql(context)
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
        imports = {
            "import sys",
            "from pathlib import Path",
            "from gcp_ml_framework.dag.operators import VertexPipelineOperator",
            "from gcp_ml_framework.config import load_config",
            "from gcp_ml_framework.context import MLContext as _MLContext",
        }

        code = f"""# Load pipeline definition for: {task.pipeline_name}
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "_pipeline_{task.pipeline_name}",
    _repo_root / "pipelines" / "{task.pipeline_name}" / "pipeline.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_pipeline_def_{name} = _mod.pipeline

_cfg = load_config(framework_yaml=_repo_root / "framework.yaml")
_ctx = _MLContext.from_config(_cfg)

{name} = VertexPipelineOperator(
    task_id="{name}",
    pipeline_name="{task.pipeline_name}",
    context=_ctx,
    pipeline_def=_pipeline_def_{name},
    enable_caching={task.enable_caching!r},
    sync={task.sync!r},
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
