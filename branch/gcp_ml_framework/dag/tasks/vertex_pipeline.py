"""VertexPipelineTask — submit a Vertex AI Pipeline as a Composer task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class VertexPipelineTask(BaseTask):
    """
    Submit a Vertex AI Pipeline as a Composer task.

    Wraps the existing VertexPipelineOperator. The pipeline is identified
    by name — the framework discovers, compiles, and submits it.
    """

    task_type: str = field(default="vertex_pipeline", init=False)
    config: TaskConfig = field(default_factory=TaskConfig)

    pipeline_name: str = ""
    enable_caching: bool = True
    sync: bool = True
    parameter_overrides: dict = field(default_factory=dict)

    def validate(self, context: MLContext) -> list[str]:
        errors: list[str] = []
        if not self.pipeline_name.strip():
            errors.append("VertexPipelineTask requires a non-empty pipeline_name")
        return errors

    def as_airflow_operator(self, context: MLContext, dag: Any, task_id: str) -> Any:
        import importlib.util
        from pathlib import Path

        from gcp_ml_framework.dag.operators import VertexPipelineOperator

        # Look for pipeline.py relative to the dag file's repo root
        # In Composer, repo root is one level up from dags/
        repo_root = Path(dag.fileloc).parent.parent if dag else Path(".")
        pipeline_path = repo_root / "pipelines" / self.pipeline_name / "pipeline.py"

        spec = importlib.util.spec_from_file_location(
            f"_pipeline_{self.pipeline_name}", pipeline_path,
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        pipeline_def = mod.pipeline

        return VertexPipelineOperator(
            task_id=task_id,
            pipeline_name=self.pipeline_name,
            context=context,
            pipeline_def=pipeline_def,
            enable_caching=self.enable_caching,
            sync=self.sync,
        )
