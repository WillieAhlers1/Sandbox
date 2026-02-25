"""
PipelineCompiler — compiles a PipelineDefinition to a KFP v2 pipeline YAML.

The compiled YAML is what gets submitted to Vertex AI Pipelines and stored in GCS
for artifact promotion (STAGE → PROD copies the YAML, never recompiles).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


class PipelineCompiler:
    """
    Wraps the KFP v2 compiler.

    Builds a @dsl.pipeline function dynamically from the PipelineDefinition
    steps, then invokes kfp.compiler.Compiler() to produce the YAML artifact.
    """

    def __init__(self, output_dir: Path | str = "compiled_pipelines") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(
        self,
        pipeline_def: PipelineDefinition,
        context: MLContext,
    ) -> Path:
        """
        Compile the pipeline to a KFP YAML file.

        Returns the path to the compiled YAML.
        """
        try:
            import kfp.compiler as kfp_compiler
        except ImportError as exc:
            raise ImportError(
                "kfp is required for compilation. Install with: pip install kfp>=2.7"
            ) from exc

        pipeline_fn = self._build_kfp_pipeline(pipeline_def, context)

        output_path = self.output_dir / f"{pipeline_def.name}.yaml"
        kfp_compiler.Compiler().compile(
            pipeline_func=pipeline_fn,
            package_path=str(output_path),
        )
        return output_path

    def _build_kfp_pipeline(self, pipeline_def: PipelineDefinition, context: MLContext):
        """
        Dynamically construct a @dsl.pipeline decorated function from the steps.

        Each step's component.as_kfp_component() provides the KFP function.
        Steps are wired in sequence using .after() for dependency ordering.
        """
        from kfp import dsl

        steps = pipeline_def.steps
        pipeline_root = context.naming.gcs_pipeline_root(pipeline_def.name)
        ctx_params = self._build_context_params(context, pipeline_def)

        @dsl.pipeline(
            name=pipeline_def.name,
            description=pipeline_def.description,
            pipeline_root=pipeline_root,
        )
        def _pipeline(run_date: str = ""):
            prev_task = None
            for step in steps:
                component_fn = step.component.as_kfp_component()
                params = {**ctx_params, **self._step_params(step, ctx_params, run_date)}
                task = component_fn(**params)
                if prev_task is not None:
                    task.after(prev_task)
                prev_task = task

        return _pipeline

    def _build_context_params(self, context: MLContext, pipeline_def: PipelineDefinition) -> dict:
        return {
            "project": context.gcp_project,
            "region": context.region,
            "dataset": context.bq_dataset,
            "gcs_prefix": context.gcs_prefix,
            "feature_store_id": context.feature_store_id,
            "staging_bucket": context.naming.gcs_bucket,
            "experiment_name": context.naming.vertex_experiment(pipeline_def.name),
        }

    def _step_params(self, step, ctx_params: dict, run_date: str) -> dict:
        """Extract component-specific params from the component dataclass fields."""
        import dataclasses
        from dataclasses import fields

        component = step.component
        extra: dict = {}

        # Pull dataclass fields (excluding component_name and config)
        if dataclasses.is_dataclass(component):
            for f in fields(component):
                if f.name in ("component_name", "config"):
                    continue
                val = getattr(component, f.name)
                if isinstance(val, (list, dict)):
                    extra[f.name] = json.dumps(val)
                else:
                    extra[f.name] = val

        return extra
