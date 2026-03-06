"""VertexPipelineTask — submit a Vertex AI Pipeline as a Composer task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


@dataclass
class VertexPipelineTask(BaseTask):
    """
    Submit a Vertex AI Pipeline as a Composer task.

    Accepts either an inline ``pipeline`` (PipelineDefinition) or a
    ``pipeline_name`` string.  When ``pipeline`` is provided, the name is
    derived automatically and the local runner can execute the pipeline
    directly without discovering a separate directory on disk.

    The DAG compiler generates a self-contained CreatePipelineJobOperator
    referencing the compiled KFP YAML at its GCS path. No framework imports
    are needed at Airflow parse time.
    """

    task_type: str = field(default="vertex_pipeline", init=False)
    config: TaskConfig = field(default_factory=TaskConfig)

    pipeline: PipelineDefinition | None = None
    pipeline_name: str = ""
    enable_caching: bool = False
    sync: bool = True
    parameter_overrides: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Derive pipeline_name from pipeline object when not explicitly set."""
        if self.pipeline is not None and not self.pipeline_name:
            self.pipeline_name = self.pipeline.name

    def validate(self, context: MLContext) -> list[str]:
        errors: list[str] = []
        if not self.pipeline_name.strip():
            errors.append(
                "VertexPipelineTask requires either a pipeline object "
                "or a non-empty pipeline_name"
            )
        return errors

    def as_airflow_operator(self, context: MLContext, dag: Any, task_id: str) -> Any:
        """Not used directly — the DAG compiler generates operator code."""
        raise NotImplementedError(
            "VertexPipelineTask does not create operators directly. "
            "The DAG compiler generates self-contained CreatePipelineJobOperator code."
        )
