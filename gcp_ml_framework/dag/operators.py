"""Custom Airflow operators for the GCP ML Framework."""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


class VertexPipelineOperator:
    """
    Airflow operator that compiles and submits a KFP v2 pipeline to Vertex AI.

    On each DAG run:
    1. Compiles the PipelineDefinition to a KFP YAML in a temp directory.
    2. Submits the compiled pipeline to Vertex AI Pipelines.
    3. Waits for completion (sync=True by default in Composer).

    Idempotent: re-submitting with the same run_id is deduplicated by Vertex AI.
    """

    def __init__(
        self,
        task_id: str,
        pipeline_name: str,
        context: MLContext,
        pipeline_def: PipelineDefinition,
        enable_caching: bool = True,
        sync: bool = True,
        **kwargs: Any,
    ) -> None:
        # Import BaseOperator lazily so the module can be imported without Airflow installed
        try:
            from airflow.models import BaseOperator  # type: ignore[import]

            class _Op(BaseOperator):
                template_fields = ("_pipeline_name",)

                def __init__(self_, **kw: Any) -> None:
                    super().__init__(task_id=task_id, **kw)
                    self_._pipeline_name = pipeline_name
                    self_._context = context
                    self_._pipeline_def = pipeline_def
                    self_._enable_caching = enable_caching
                    self_._sync = sync

                def execute(self_, airflow_context: dict) -> str:
                    from gcp_ml_framework.pipeline.compiler import PipelineCompiler
                    from gcp_ml_framework.pipeline.runner import VertexRunner

                    with tempfile.TemporaryDirectory() as tmpdir:
                        compiler = PipelineCompiler(output_dir=tmpdir)
                        run_date = str(airflow_context.get("ds", ""))
                        compiled = compiler.compile(self_._pipeline_def, self_._context)
                        runner = VertexRunner(self_._context)
                        job = runner.submit(
                            compiled_path=compiled,
                            pipeline_name=self_._pipeline_name,
                            parameter_values={"run_date": run_date},
                            enable_caching=self_._enable_caching,
                            sync=self_._sync,
                        )
                        return job.resource_name

            self._op = _Op(**kwargs)

        except ImportError:
            # Airflow not installed — store params for testing
            self._op = None
            self._task_id = task_id
            self._pipeline_name = pipeline_name
            self._context = context
            self._pipeline_def = pipeline_def

    def __repr__(self) -> str:
        return f"VertexPipelineOperator(task_id={self._task_id if self._op is None else self._op.task_id!r})"
