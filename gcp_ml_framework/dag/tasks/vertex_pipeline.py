"""VertexPipelineTask — submit a Vertex AI Pipeline as a Composer task."""

from __future__ import annotations

from pydantic import ConfigDict, Field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig
# Change: Fix Pydantic forward reference errors
from gcp_ml_framework.pipeline.builder import PipelineDefinition

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


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

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_type: str = "vertex_pipeline"
    config: TaskConfig = Field(default_factory=TaskConfig)

    pipeline: PipelineDefinition | None = None
    pipeline_name: str = ""
    enable_caching: bool = False
    sync: bool = True
    parameter_overrides: dict = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
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
