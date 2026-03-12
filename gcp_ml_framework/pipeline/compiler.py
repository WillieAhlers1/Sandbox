"""
PipelineCompiler — compiles a PipelineDefinition to a KFP v2 pipeline YAML.

The compiled YAML is what gets submitted to Vertex AI Pipelines and stored in GCS
for artifact promotion (STAGE → PROD copies the YAML, never recompiles).
"""

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

    def __init__(self, output_dir: "Path | str" = "compiled_pipelines") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(
        self,
        pipeline_def: "PipelineDefinition",
        context: "MLContext",
        pipeline_dir: "Path | None" = None,
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

        pipeline_fn = self._build_kfp_pipeline(pipeline_def, context, pipeline_dir)

        output_path = self.output_dir / f"{pipeline_def.name}.yaml"
        kfp_compiler.Compiler().compile(
            pipeline_func=pipeline_fn,
            package_path=str(output_path),
        )
        return output_path

    def _build_kfp_pipeline(
        self,
        pipeline_def: "PipelineDefinition",
        context: "MLContext",
        pipeline_dir: "Path | None" = None,
    ):
        """
        Dynamically construct a @dsl.pipeline decorated function from the steps.

        Each step's component.as_kfp_component() provides the KFP function.
        Steps are wired in sequence using .after() for dependency ordering.
        Cross-step data flow is wired via prev_task.output.
        """
        from kfp import dsl

        steps = pipeline_def.steps
        pipeline_root = context.naming.gcs_pipeline_root(pipeline_def.name)
        ctx_params = self._build_context_params(context, pipeline_def)
        derived_params = self._build_derived_params(context, pipeline_def, steps, pipeline_dir)

        # Resolve the pre-built component base image so steps skip runtime pip install
        component_base_image = context.naming.image_uri(
            registry_host=context.artifact_registry_host,
            gcp_project=context.gcp_project,
            image_name="component-base",
        )

        @dsl.pipeline(
            name=pipeline_def.name,
            description=pipeline_def.description,
            pipeline_root=pipeline_root,
        )
        def _pipeline(run_date: str = ""):
            prev_task = None
            last_dataset_output = None  # output from data-producing steps (ingest/transform)
            last_model_output = None  # output from train step
            for step in steps:
                component_fn = step.component.as_kfp_component(base_image=component_base_image)
                step_extra = derived_params.get(step.name, {})
                all_params = {
                    **ctx_params,
                    **self._step_params(step, ctx_params, run_date),
                    **step_extra,
                }
                # Only pass params the component actually accepts
                accepted = set(component_fn.component_spec.inputs or {})
                params = {k: v for k, v in all_params.items() if k in accepted}

                # Wire cross-step data flow from tracked outputs
                if last_dataset_output is not None:
                    for key in ("dataset_uri", "eval_dataset_uri", "bq_source_table"):
                        if key in accepted and key not in params:
                            params[key] = last_dataset_output
                if (
                    last_model_output is not None
                    and "model_uri" in accepted
                    and "model_uri" not in params
                ):
                    params["model_uri"] = last_model_output

                task = component_fn(**params)
                if prev_task is not None:
                    task.after(prev_task)
                prev_task = task

                # Track output — train steps produce model outputs, others produce datasets.
                # WriteFeatures is metadata-only (registers a BQ table as a FeatureGroup)
                # and should not overwrite the dataset output for downstream steps.
                if component_fn.component_spec.outputs:
                    is_train = hasattr(step.component, "trainer_image")
                    is_metadata_only = step.component.component_name in (
                        "write_features",
                    )
                    # @dsl.container_component uses named outputs (e.g. output_uri),
                    # while @dsl.component uses task.output (return value).
                    outputs = component_fn.component_spec.outputs
                    if "output_uri" in outputs:
                        task_output = task.outputs["output_uri"]
                    else:
                        task_output = task.output
                    if is_train:
                        last_model_output = task_output
                    elif not is_metadata_only:
                        last_dataset_output = task_output

        return _pipeline

    def _build_context_params(
        self, context: "MLContext", pipeline_def: "PipelineDefinition"
    ) -> dict:
        return {
            "project": context.gcp_project,
            "region": context.region,
            "dataset": context.bq_dataset,
            "gcs_prefix": context.gcs_prefix,
            "feature_store_id": context.feature_store_id,
            "staging_bucket": context.naming.gcs_bucket,
            "experiment_name": context.naming.vertex_experiment(pipeline_def.name),
            "artifact_registry": context.naming.artifact_registry_repo(
                context.artifact_registry_host,
                context.gcp_project,
            ),
        }

    def _build_derived_params(
        self,
        context: "MLContext",
        pipeline_def: "PipelineDefinition",
        steps: list,
        pipeline_dir: "Path | None" = None,
    ) -> dict:
        """Compute per-step derived params that aren't simple dataclass fields."""
        derived: dict[str, dict] = {}
        for step in steps:
            comp = step.component
            extra: dict = {}

            # WriteFeatures / ReadFeatures: need feature_view_id and feature_group_id
            if hasattr(comp, "entity") and hasattr(comp, "feature_group"):
                fv_id = context.naming.feature_view_id(comp.entity, comp.feature_group)
                extra["feature_view_id"] = fv_id
                extra["feature_group_id"] = fv_id

            # TrainModel: needs job_name, model_output_uri, and resolved trainer_image
            if hasattr(comp, "trainer_image"):
                extra["job_name"] = context.naming.vertex_training_job_name(pipeline_def.name)
                extra["model_output_uri"] = context.naming.gcs_model_path(pipeline_def.name)
                extra["trainer_image"] = comp.resolve_image_uri(
                    pipeline_def.name, context, pipeline_dir
                )

            # DeployModel: needs model_display_name and endpoint_display_name
            if hasattr(comp, "endpoint_name"):
                extra["model_display_name"] = context.naming.vertex_model_name(pipeline_def.name)
                extra["endpoint_display_name"] = context.naming.vertex_endpoint_name(
                    comp.endpoint_name
                )

            if extra:
                derived[step.name] = extra
        return derived

    def _step_params(self, step, ctx_params: dict, run_date: str) -> dict:
        """Extract component-specific params from the component dataclass fields."""
        import dataclasses
        from dataclasses import fields

        component = step.component
        extra: dict = {}

        # Pull dataclass fields (excluding component_name, config, and None values)
        if dataclasses.is_dataclass(component):
            for f in fields(component):
                if f.name in ("component_name", "config"):
                    continue
                val = getattr(component, f.name)
                if val is None:
                    continue
                if isinstance(val, (list, dict)):
                    extra[f.name] = json.dumps(val)
                else:
                    extra[f.name] = val

        extra["run_date"] = run_date

        # Resolve {artifact_registry} placeholder in string values
        ar = ctx_params.get("artifact_registry", "")
        if ar:
            for k, v in extra.items():
                if isinstance(v, str) and "{artifact_registry}" in v:
                    extra[k] = v.replace("{artifact_registry}", ar)

        return extra
