"""
Pipeline runners.

VertexRunner  — submits a compiled KFP YAML to Vertex AI Pipelines.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


class VertexRunner:
    """
    Submit a compiled KFP pipeline YAML to Vertex AI Pipelines.
    """

    def __init__(self, context: MLContext) -> None:
        self._ctx = context

    def submit(
        self,
        compiled_path: Path,
        pipeline_name: str,
        parameter_values: dict | None = None,
        enable_caching: bool = False,
        sync: bool = False,
    ) -> Any:
        """
        Submit the pipeline and optionally wait for completion.

        Returns the aiplatform.PipelineJob object.
        """
        try:
            from google.cloud import aiplatform  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-aiplatform is required. "
                "Install with: pip install google-cloud-aiplatform"
            ) from exc

        aiplatform.init(
            project=self._ctx.gcp_project,
            location=self._ctx.region,
            staging_bucket=f"gs://{self._ctx.naming.gcs_bucket}",
        )

        job = aiplatform.PipelineJob(
            display_name=self._ctx.naming.vertex_pipeline_display_name(pipeline_name),
            template_path=str(compiled_path),
            pipeline_root=self._ctx.naming.gcs_pipeline_root(pipeline_name),
            parameter_values=parameter_values or {},
            enable_caching=enable_caching,
        )
        job.submit(service_account=self._ctx.pipeline_service_account)
        if sync:
            job.wait()
        return job
