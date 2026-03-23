"""
PipelineCompiler — compiles a PipelineDefinition to a KFP v2 pipeline YAML.

The compiled YAML is what gets submitted to Vertex AI Pipelines and stored in GCS
for artifact promotion (STAGE → PROD copies the YAML, never recompiles).
"""

import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.train import TrainModel

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

        # Default pipeline image — used when serving_dockerfile is not set
        default_image = self._resolve_image_uri(context, None)

        derived_params = self._build_derived_params(
            context, pipeline_def, steps, pipeline_dir, default_image
        )

        @dsl.pipeline(
            name=pipeline_def.name,
            description=pipeline_def.description,
            pipeline_root=pipeline_root,
        )
        def _pipeline(
            run_date: str = "",
            dataset_uri: str = "",
            model_uri: str = "",
        ):
            prev_task = None
            last_dataset_output = None  # output from data-producing steps (ingest/transform)
            last_model_output = None  # output from train step
            for step in steps:
                # Derive step_module from the component's class module path
                step_module = step.component.__class__.__module__
                # Resolve per-component image from runtime_dockerfile
                step_image = self._resolve_image_uri(context, step.component.runtime_dockerfile)
                component_fn = step.component.as_kfp_component(
                    step_module=step_module,
                    base_image=step_image,
                )
                step_extra = derived_params.get(step.name, {})

                # Build flat param dict: component fields (base), then context + derived overlay
                from gcp_ml_framework.components.base import _INTERNAL_FIELDS

                component_fields = {}
                for name in type(step.component).model_fields:
                    if name in _INTERNAL_FIELDS:
                        continue
                    val = getattr(step.component, name)
                    if val is None:
                        continue
                    component_fields[name] = val
                # Component fields are the base; context and derived params override them
                merged = {**component_fields, **ctx_params, **step_extra}

                # Inject bridged params from pipeline inputs
                # (may be overridden by cross-step wiring below)
                if dataset_uri:
                    merged["dataset_uri"] = dataset_uri
                if model_uri:
                    merged["model_uri"] = model_uri

                # Wire cross-step data flow from tracked outputs
                if last_dataset_output is not None:
                    merged["dataset_uri"] = last_dataset_output
                if last_model_output is not None:
                    merged["model_uri"] = last_model_output

                # Inject run_date from pipeline param
                merged["run_date"] = run_date

                # Filter to only params the component declares as KFP inputs
                accepted = set(component_fn.component_spec.inputs or {})  # type: ignore[attr-defined]
                call_kwargs = {}
                for k, v in merged.items():
                    if k not in accepted:
                        continue
                    # Serialize non-string values to JSON strings for KFP
                    if isinstance(v, (dict, list)):
                        call_kwargs[k] = json.dumps(v)
                    elif not isinstance(v, str):
                        call_kwargs[k] = str(v)
                    else:
                        call_kwargs[k] = v

                task = component_fn(**call_kwargs)
                task.set_display_name(step.name)
                if prev_task is not None:
                    task.after(prev_task)
                prev_task = task

                # Track output — train/register → model output, others → dataset.
                # WriteFeatures is metadata-only and should not overwrite dataset output.
                if component_fn.component_spec.outputs:  # type: ignore[attr-defined]
                    is_model_producer = isinstance(step.component, (TrainModel, RegisterModel))
                    is_metadata_only = isinstance(step.component, WriteFeatures)
                    task_output = task.outputs["output_uri"]
                    if is_model_producer:
                        last_model_output = task_output
                    elif not is_metadata_only:
                        last_dataset_output = task_output

            # ── Loop blocks: dsl.ParallelFor ─────────────────────
            for loop_block in pipeline_def.loop_blocks:
                with dsl.ParallelFor(
                    items=loop_block.items,
                    name=f"loop_{loop_block.index}",
                ) as loop_item:
                    loop_prev = prev_task
                    for step in loop_block.steps:
                        step_module = step.component.__class__.__module__
                        step_image = self._resolve_image_uri(
                            context, step.component.runtime_dockerfile
                        )
                        component_fn = step.component.as_kfp_component(
                            step_module=step_module,
                            base_image=step_image,
                        )
                        step_extra = derived_params.get(step.name, {})
                        comp_fields = {}
                        for fname in type(step.component).model_fields:
                            if fname in _INTERNAL_FIELDS:
                                continue
                            val = getattr(step.component, fname)
                            if val is not None:
                                comp_fields[fname] = val
                        merged = {**comp_fields, **ctx_params, **step_extra}
                        merged["run_date"] = run_date
                        # Inject loop variable into the designated param
                        merged[loop_block.item_param] = loop_item

                        accepted = set(
                            component_fn.component_spec.inputs or {}  # type: ignore[attr-defined]
                        )
                        call_kwargs = {}
                        for k, v in merged.items():
                            if k not in accepted:
                                continue
                            if isinstance(v, (dict, list)):
                                call_kwargs[k] = json.dumps(v)
                            elif not isinstance(v, str):
                                call_kwargs[k] = str(v)
                            else:
                                call_kwargs[k] = v

                        task = component_fn(**call_kwargs)
                        task.set_display_name(step.name)
                        if loop_prev is not None:
                            task.after(loop_prev)
                        loop_prev = task

            # ── Condition blocks: dsl.If ─────────────────────────
            # MVP: conditions reference the last sequential task's output
            for cond_block in pipeline_def.condition_blocks:
                # MVP: condition checks the last sequential task's output
                if prev_task is not None and hasattr(prev_task, "outputs"):
                    source_output = prev_task.outputs.get(
                        cond_block.output_key, prev_task.outputs.get("output_uri")
                    )
                    if source_output is not None:
                        # Build comparison
                        op = cond_block.operator
                        val = cond_block.value
                        if op == "!=":
                            cond_expr = source_output != val
                        elif op == "==":
                            cond_expr = source_output == val
                        elif op == ">":
                            cond_expr = source_output > val
                        elif op == "<":
                            cond_expr = source_output < val
                        elif op == ">=":
                            cond_expr = source_output >= val
                        elif op == "<=":
                            cond_expr = source_output <= val
                        else:
                            cond_expr = source_output != val

                        with dsl.If(cond_expr, name=f"condition_{cond_block.index}"):
                            cond_prev = prev_task
                            for step in cond_block.then_steps:
                                step_module = step.component.__class__.__module__
                                step_image = self._resolve_image_uri(
                                    context, step.component.runtime_dockerfile
                                )
                                component_fn = step.component.as_kfp_component(
                                    step_module=step_module,
                                    base_image=step_image,
                                )
                                step_extra = derived_params.get(step.name, {})
                                comp_fields = {}
                                for fname in type(step.component).model_fields:
                                    if fname in _INTERNAL_FIELDS:
                                        continue
                                    val2 = getattr(step.component, fname)
                                    if val2 is not None:
                                        comp_fields[fname] = val2
                                merged = {**comp_fields, **ctx_params, **step_extra}
                                merged["run_date"] = run_date

                                accepted = set(
                                    component_fn.component_spec.inputs or {}  # type: ignore[attr-defined]
                                )
                                call_kwargs = {}
                                for k, v in merged.items():
                                    if k not in accepted:
                                        continue
                                    if isinstance(v, (dict, list)):
                                        call_kwargs[k] = json.dumps(v)
                                    elif not isinstance(v, str):
                                        call_kwargs[k] = str(v)
                                    else:
                                        call_kwargs[k] = v

                                task = component_fn(**call_kwargs)
                                task.set_display_name(step.name)
                                if cond_prev is not None:
                                    task.after(cond_prev)
                                cond_prev = task

        return _pipeline

    @staticmethod
    def _parse_dockerfile_path(dockerfile_path: str) -> tuple[str | None, str]:
        """Extract pipeline_name and dockerfile_stem from a dockerfile path.

        The path is relative to the docker/ directory:
            "pipelines/house_price/regression_serve.Dockerfile"
            → pipeline_name="house_price", stem="regression_serve"

            "train.Dockerfile"
            → pipeline_name=None, stem="train"

        Returns:
            (pipeline_name, dockerfile_stem)
        """
        p = PurePosixPath(dockerfile_path)
        stem = p.stem  # "regression_serve" from "regression_serve.Dockerfile"
        parts = p.parts
        if len(parts) >= 3 and parts[0] == "pipelines":
            # docker/pipelines/{pipeline_name}/{file}.Dockerfile
            return parts[1], stem
        # Root-level: docker/{file}.Dockerfile
        return None, stem

    def _resolve_image_uri(
        self,
        context: "MLContext",
        dockerfile_path: str | None,
    ) -> str:
        """Resolve a dockerfile path to a full AR image URI.

        Uses NamingConvention.docker_image_uri() — the single source of truth
        for image naming shared with docker_build.sh.

        Args:
            context: Runtime context with AR host, project, naming.
            dockerfile_path: Path relative to docker/ (e.g.,
                "pipelines/house_price/regression_serve.Dockerfile"), or None
                for the default training image.
        """
        if dockerfile_path is None:
            # Default: root-level train.Dockerfile
            return context.naming.docker_image_uri(
                registry_host=context.artifact_registry_host,
                gcp_project=context.gcp_project,
                pipeline_name=None,
                dockerfile_stem="train",
            )
        pipeline_name, stem = self._parse_dockerfile_path(dockerfile_path)
        return context.naming.docker_image_uri(
            registry_host=context.artifact_registry_host,
            gcp_project=context.gcp_project,
            pipeline_name=pipeline_name,
            dockerfile_stem=stem,
        )

    def _build_context_params(
        self, context: "MLContext", pipeline_def: "PipelineDefinition"
    ) -> dict:
        return {
            "project": context.gcp_project,
            "region": context.region,
            "project_name": context.naming.project,
            "branch": context.naming.branch,
            "environment": context.environment.value,
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
        default_image: str = "",
    ) -> dict:
        """Compute per-step derived params that aren't simple dataclass fields."""
        derived: dict[str, dict] = {}
        for step in steps:
            comp = step.component
            extra: dict = {}

            # WriteFeatures: need feature_view_id and feature_group_id
            if hasattr(comp, "entity") and hasattr(comp, "feature_group"):
                fv_id = context.naming.feature_view_id(comp.entity, comp.feature_group)
                extra["feature_view_id"] = fv_id
                extra["feature_group_id"] = fv_id

            # TrainModel: needs job_name and model_output_uri
            if isinstance(comp, TrainModel):
                extra["job_name"] = context.naming.vertex_training_job_name(pipeline_def.name)
                extra["model_output_uri"] = context.naming.gcs_model_path(pipeline_def.name)

            # RegisterModel: needs model_display_name + serving_container_image
            # Serving image resolution (uses serving_dockerfile, NOT runtime_dockerfile):
            #   1. serving_container_image (full URI) — use as-is
            #   2. serving_dockerfile — resolve via naming convention
            #   3. Neither set — fall back to pipeline default training image
            if isinstance(comp, RegisterModel):
                extra["model_display_name"] = context.naming.vertex_model_name(
                    pipeline_def.name, comp.model_name or None
                )
                if not comp.serving_container_image:
                    if comp.serving_dockerfile:
                        extra["serving_container_image"] = self._resolve_image_uri(
                            context, comp.serving_dockerfile
                        )
                    elif default_image:
                        extra["serving_container_image"] = default_image

            # DeployModel: needs model_display_name and endpoint_display_name.
            # Both are derived from pipeline_name + model_name via naming convention.
            # No serving image needed — it's already captured during registration.
            if isinstance(comp, DeployModel):
                model_name_val = comp.model_name or None
                extra["model_display_name"] = context.naming.vertex_model_name(
                    pipeline_def.name, model_name_val
                )
                extra["endpoint_display_name"] = context.naming.vertex_endpoint_name(
                    pipeline_def.name, model_name_val
                )

            if extra:
                derived[step.name] = extra
        return derived
