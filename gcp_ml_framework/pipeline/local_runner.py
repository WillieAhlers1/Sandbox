"""LocalRunner — execute unified pipelines in-process against real GCP resources.

Runs all steps sequentially regardless of task_type. Each component's execute()
method is called directly with context-derived params merged in.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from loguru import logger

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.train import TrainModel

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


class LocalRunner:
    """Execute a unified pipeline definition in-process.

    All steps run sequentially in the current Python process, calling
    component.execute() directly. This is the ``gml run --local`` path.

    No Airflow, no KFP, no containers — just direct Python calls against
    real GCP dev resources.
    """

    def run(
        self,
        pipeline_def: PipelineDefinition,
        context: MLContext,
        run_date: str = "",
    ) -> None:
        """Execute all steps in-process."""
        if pipeline_def.has_control_flow:
            raise NotImplementedError(
                "LocalRunner does not support for_each() or condition() blocks. "
                "Use 'gml run <pipeline>' (via Composer) for pipelines with control flow."
            )

        from gcp_ml_framework.components.base import _INTERNAL_FIELDS
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        run_date = run_date or datetime.date.today().isoformat()

        # Build context params (same logic as PipelineCompiler)
        compiler = PipelineCompiler()
        ctx_params = compiler._build_context_params(context, pipeline_def)
        derived_params = compiler._build_derived_params(context, pipeline_def, pipeline_def.steps)

        last_dataset_output: str | None = None
        last_model_output: str | None = None

        for step in pipeline_def.steps:
            logger.info(f"[local] Running step: {step.name} ({step.task_type})")

            # Build param dict: component fields → context → derived → cross-step
            component_fields = {}
            for name in type(step.component).model_fields:
                if name in _INTERNAL_FIELDS:
                    continue
                val = getattr(step.component, name)
                if val is None:
                    continue
                component_fields[name] = val

            step_extra = derived_params.get(step.name, {})
            merged = {**component_fields, **ctx_params, **step_extra}

            # Wire cross-step data flow
            comp_fields = type(step.component).model_fields
            if last_dataset_output is not None and "dataset_uri" in comp_fields:
                merged["dataset_uri"] = last_dataset_output
            if last_model_output is not None and "model_uri" in comp_fields:
                merged["model_uri"] = last_model_output

            merged["run_date"] = run_date

            # Filter to only fields the component declares
            accepted = set(type(step.component).model_fields.keys())
            filtered = {k: v for k, v in merged.items() if k in accepted}

            # Instantiate a fresh component with merged params and execute
            component_cls = type(step.component)
            instance = component_cls(**filtered)

            logger.info(f"[local] Executing {component_cls.__name__}")
            instance.execute()

            # Track outputs for cross-step wiring.
            # In local mode output_uri_path is empty (it's a KFP mechanism),
            # so we extract outputs directly from component fields.
            output = self._extract_output(instance, context)
            if output is not None:
                is_model_producer = isinstance(instance, (TrainModel, RegisterModel))
                is_metadata_only = isinstance(instance, WriteFeatures)
                if is_model_producer:
                    last_model_output = output
                elif not is_metadata_only:
                    last_dataset_output = output

            logger.info(f"[local] Step '{step.name}' completed")

        step_count = len(pipeline_def.steps)
        logger.info(f"[local] Pipeline '{pipeline_def.name}' finished ({step_count} steps)")

    @staticmethod
    def _extract_output(instance: object, context: MLContext) -> str | None:
        """Extract the output value from a component after execute().

        In local mode, output_uri_path (the KFP file mechanism) is not set.
        Instead we read the actual output directly from component fields:
        - TrainModel: model_output_uri (GCS path where model was uploaded)
        - BQQuery: project.dataset.destination_table
        - BQTransform: project.dataset.output_table
        """
        # TrainModel → GCS model path
        if isinstance(instance, TrainModel) and instance.model_output_uri:
            return instance.model_output_uri

        # BQQuery → deterministic table reference
        if hasattr(instance, "destination_table") and instance.destination_table:
            return f"{context.gcp_project}.{context.bq_dataset}.{instance.destination_table}"

        # BQTransform → deterministic table reference
        if hasattr(instance, "output_table") and instance.output_table:
            return f"{context.gcp_project}.{context.bq_dataset}.{instance.output_table}"

        return None
