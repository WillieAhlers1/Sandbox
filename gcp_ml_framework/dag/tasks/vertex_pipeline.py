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

    The DAG compiler generates a self-contained CreatePipelineJobOperator
    referencing the compiled KFP YAML at its GCS path. No framework imports
    are needed at Airflow parse time.
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
        """Not used directly — the DAG compiler generates operator code."""
        raise NotImplementedError(
            "VertexPipelineTask does not create operators directly. "
            "The DAG compiler generates self-contained CreatePipelineJobOperator code."
        )
