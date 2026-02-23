"""
DAGFactory — generates Airflow DAGs from PipelineDefinitions.

The schedule comes from PipelineDefinition.schedule (set via PipelineBuilder),
which is the single source of truth. It flows through to the Composer DAG's
schedule_interval automatically.

Two modes:
1. make_dag()          — called at Composer import time to produce a live DAG object.
2. render_dag_file()   — generates the Python source for a DAG file that is synced
                         to the Composer GCS bucket by `gml deploy dags`.
"""

from __future__ import annotations

from datetime import timedelta
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


def make_dag(pipeline_def: "PipelineDefinition", context: "MLContext"):
    """
    Build and return an Airflow DAG from a PipelineDefinition.

    Called at Composer import time. The DAG compiles and submits the Vertex AI
    pipeline on each run via VertexPipelineOperator.
    """
    try:
        from airflow import DAG  # type: ignore[import]
        from airflow.utils.dates import days_ago
    except ImportError as exc:
        raise ImportError(
            "apache-airflow is required. Install with: pip install apache-airflow>=2.8"
        ) from exc

    from gcp_ml_framework.dag.operators import VertexPipelineOperator

    dag_id = context.naming.dag_id(pipeline_def.name)

    with DAG(
        dag_id=dag_id,
        description=pipeline_def.description or f"GML pipeline: {pipeline_def.name}",
        schedule_interval=pipeline_def.schedule,
        start_date=days_ago(1),
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


class DAGFactory:
    """Static factory for DAG file generation (used by `gml deploy dags`)."""

    @staticmethod
    def render_dag_file(pipeline_name: str, context: "MLContext") -> str:
        """
        Render the Python source of an Airflow DAG file for the given pipeline.

        The generated file:
        - Imports the pipeline definition from pipelines/{name}/pipeline.py
        - Loads config from framework.yaml (auto-discovered)
        - Calls make_dag() to produce the DAG object for Composer
        """
        return f'''\
"""
Auto-generated Airflow DAG for pipeline: {pipeline_name}
Branch namespace: {context.namespace}
GCP project: {context.gcp_project}

DO NOT EDIT MANUALLY.
Regenerate with: gml deploy dags
"""
import sys
from pathlib import Path

# Allow importing pipelines from the repo root
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from gcp_ml_framework.config import load_config
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.dag.factory import make_dag

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "_pipeline_{pipeline_name}",
    _repo_root / "pipelines" / "{pipeline_name}" / "pipeline.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_pipeline_def = _mod.pipeline

_cfg = load_config(
    framework_yaml=_repo_root / "framework.yaml",
    pipeline_yaml=_repo_root / "pipelines" / "{pipeline_name}" / "config.yaml"
    if (_repo_root / "pipelines" / "{pipeline_name}" / "config.yaml").exists()
    else None,
)
_context = MLContext.from_config(_cfg)

dag = make_dag(_pipeline_def, _context)
'''
