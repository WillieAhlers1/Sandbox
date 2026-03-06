"""
DAGFactory — generates Airflow DAGs from PipelineDefinitions and DAGDefinitions.

Two paths:
1. Pipeline has a dag.py (DAGBuilder) → use DAGCompiler directly.
2. Pipeline has only pipeline.py (PipelineBuilder) → auto-wrap in a single
   VertexPipelineTask via DAGBuilder, then compile.

The make_dag() function is kept for backward compatibility with any code that
calls it directly.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


_DEFAULT_ARGS = {
    "owner": "gcp-mlf",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
}


def make_dag(pipeline_def: PipelineDefinition, context: MLContext):
    """
    Build and return an Airflow DAG from a PipelineDefinition.

    Kept for backward compatibility. New code should use DAGBuilder + DAGCompiler.
    """
    try:
        from datetime import datetime

        from airflow import DAG  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "apache-airflow is required. Install with: pip install apache-airflow>=2.8"
        ) from exc

    from gcp_ml_framework.dag.operators import VertexPipelineOperator

    dag_id = context.naming.dag_id(pipeline_def.name)

    with DAG(
        dag_id=dag_id,
        description=pipeline_def.description or f"GML pipeline: {pipeline_def.name}",
        schedule=pipeline_def.schedule,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        max_active_runs=1,
        tags=[context.naming.team, context.naming.project, context.naming.branch]
              + pipeline_def.tags,
        default_args=_DEFAULT_ARGS,
    ) as dag:
        VertexPipelineOperator(
            task_id="run_vertex_pipeline",
            pipeline_name=pipeline_def.name,
            context=context,
            pipeline_def=pipeline_def,
        )

    return dag


def auto_wrap_pipeline_dag(
    pipeline_def: PipelineDefinition, context: MLContext, dags_dir: Path | str = "dags"
) -> Path:
    """
    Auto-generate and write a DAG file for a PipelineBuilder pipeline.

    Returns the written file path.
    """
    dags_dir = Path(dags_dir)
    dags_dir.mkdir(parents=True, exist_ok=True)
    dag_id = context.naming.dag_id(pipeline_def.name)
    content = auto_dag_for_pipeline(pipeline_def, context)
    output_path = dags_dir / f"{dag_id}.py"
    output_path.write_text(content)
    return output_path


def auto_dag_for_pipeline(pipeline_def: PipelineDefinition, context: MLContext) -> str:
    """
    Auto-generate a DAG file for a PipelineBuilder pipeline that has no custom dag.py.

    Wraps the pipeline in a single VertexPipelineTask — equivalent to the old
    DAGFactory.render_dag_file() behavior.
    """
    from gcp_ml_framework.dag.builder import DAGBuilder
    from gcp_ml_framework.dag.compiler import DAGCompiler
    from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

    dag_def = (
        DAGBuilder(
            name=pipeline_def.name,
            schedule=pipeline_def.schedule,
            description=pipeline_def.description,
            tags=pipeline_def.tags,
        )
        .task(
            VertexPipelineTask(pipeline_name=pipeline_def.name),
            name="run_vertex_pipeline",
        )
        .build()
    )
    compiler = DAGCompiler()
    return compiler.render(dag_def, context)


def render_dag_from_definition(
    dag_def, context: MLContext, pipeline_dir: Path | None = None
) -> str:
    """Render a DAGDefinition (from dag.py) to an Airflow DAG file."""
    from gcp_ml_framework.dag.compiler import DAGCompiler

    compiler = DAGCompiler(pipeline_dir=pipeline_dir)
    return compiler.render(dag_def, context)


def discover_and_render(
    pipeline_dir: Path, context: MLContext
) -> tuple[str, str]:
    """
    Discover whether a pipeline directory has dag.py or pipeline.py, and render.

    Returns (dag_filename, dag_file_content).
    """
    dag_py = pipeline_dir / "dag.py"
    pipeline_py = pipeline_dir / "pipeline.py"

    if dag_py.exists():
        # Load the DAGDefinition from dag.py
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            f"_dag_{pipeline_dir.name}", dag_py,
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        dag_def = mod.dag
        dag_id = context.naming.dag_id(dag_def.name)
        content = render_dag_from_definition(dag_def, context, pipeline_dir=pipeline_dir)
        return f"{dag_id}.py", content

    if pipeline_py.exists():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            f"_pipeline_{pipeline_dir.name}", pipeline_py,
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        pipeline_def = mod.pipeline
        dag_id = context.naming.dag_id(pipeline_def.name)
        content = auto_dag_for_pipeline(pipeline_def, context)
        return f"{dag_id}.py", content

    raise FileNotFoundError(
        f"No dag.py or pipeline.py found in {pipeline_dir}"
    )
