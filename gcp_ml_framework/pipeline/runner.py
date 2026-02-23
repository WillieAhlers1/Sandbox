"""
Pipeline runners.

LocalRunner   — runs pipeline steps sequentially using local stubs (no GCP).
VertexRunner  — submits a compiled KFP YAML to Vertex AI Pipelines.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


class LocalRunner:
    """
    Execute a pipeline locally by calling each component's local_run() method
    in topological order (linear for now — steps run sequentially).

    GCS/BQ/Vertex SDK calls are replaced by DuckDB + pandas + temp file stubs.
    Useful for:
    - Local iteration without GCP access
    - Unit and integration tests
    - CI compile-only checks (--dry-run)
    """

    def __init__(self, context: "MLContext") -> None:
        self._ctx = context

    def print_plan(self, pipeline_def: "PipelineDefinition") -> None:
        print(f"\nPipeline: {pipeline_def.name!r}  (schedule={pipeline_def.schedule!r})")
        print(f"{'Step':<30} {'Stage':<20} {'Component'}")
        print("-" * 70)
        for step in pipeline_def.steps:
            print(f"  {step.name:<28} {step.stage:<20} {step.component.__class__.__name__}")
        print()

    def run(
        self,
        pipeline_def: "PipelineDefinition",
        run_date: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Execute all steps in order. Each step receives the output of the previous
        step as its primary input (where applicable).

        Returns a dict of {step_name: output}.
        """
        outputs: dict[str, Any] = {}
        prev_output: Any = None

        for step in pipeline_def.steps:
            if dry_run:
                print(f"[dry-run] {step.name} ({step.component.__class__.__name__})")
                continue

            print(f"[local] {step.name} ({step.component.__class__.__name__}) ...")
            try:
                kwargs: dict[str, Any] = {"run_date": run_date}
                # Wire the previous step's output as input to the next step
                if prev_output is not None:
                    kwargs["input_path"] = prev_output

                result = step.component.local_run(self._ctx, **kwargs)
                outputs[step.name] = result
                prev_output = result
                print(f"[local]   → {result}")
            except Exception as exc:
                print(f"[local]   FAILED: {exc}")
                raise

        return outputs


class VertexRunner:
    """
    Submit a compiled KFP pipeline YAML to Vertex AI Pipelines.
    """

    def __init__(self, context: "MLContext") -> None:
        self._ctx = context

    def submit(
        self,
        compiled_path: Path,
        pipeline_name: str,
        parameter_values: dict | None = None,
        enable_caching: bool = True,
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
                "google-cloud-aiplatform is required. Install with: pip install google-cloud-aiplatform"
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
        job.submit(service_account=self._ctx.service_account_email)
        if sync:
            job.wait()
        return job
