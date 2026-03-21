"""
PipelineBuilder / Pipeline — fluent DSL for defining ML pipelines.

A data scientist edits exactly one file (pipeline.py) to define their pipeline.
No KFP YAML, no Airflow DAG code, no operator wiring.

PipelineBuilder usage (explicit stage methods):
    pipeline = (
        PipelineBuilder(name="churn-prediction", schedule="0 6 * * 1")
        .ingest(BigQueryExtract(...))
        .transform(BQTransform(...))
        .train(TrainModel(...))
        .build()
    )

Pipeline usage (unified .add() with stage inference):
    pipeline = (
        Pipeline(name="churn-prediction", schedule="0 6 * * 1")
        .add(BQQuery(sql="SELECT ..."))
        .add(TrainModel(machine_type="n2-standard-8"), name="Train Churn Model")
        .add(Email(to=["team@co.com"], subject="Done"))
        .build()
    )
"""

from __future__ import annotations

from itertools import groupby

from pydantic import BaseModel, Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType


class PipelineStep(BaseModel):
    """A single step in the pipeline, wrapping a component and its position."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    component: BaseComponent
    stage: str  # 'ingest' | 'transform' | 'write_features' | 'train' | 'evaluate' | 'deploy' | ...
    task_type: TaskType = TaskType.ML_TASK


class PipelineDefinition(BaseModel):
    """
    The compiled pipeline definition produced by PipelineBuilder.build() or Pipeline.build().

    This is the object passed to:
    - PipelineCompiler / SmartCompiler (→ KFP YAML + Airflow DAG)
    - LocalRunner (→ in-process execution)
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str
    schedule: str | None
    steps: list[PipelineStep] = Field(default_factory=list)
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    @property
    def has_mixed_types(self) -> bool:
        """True if the pipeline contains both @task and @ml_task steps."""
        types = {s.task_type for s in self.steps}
        return len(types) > 1

    @property
    def ml_task_groups(self) -> list[list[PipelineStep]]:
        """Return groups of consecutive ML_TASK steps.

        Used by SmartCompiler to decide which step sequences become
        Vertex AI pipeline YAML files.
        """
        groups = []
        for task_type, group_iter in groupby(self.steps, key=lambda s: s.task_type):
            if task_type == TaskType.ML_TASK:
                groups.append(list(group_iter))
        return groups


# ---------------------------------------------------------------------------
# Stage inference map for Pipeline.add()
# ---------------------------------------------------------------------------

# Lazy-loaded to avoid circular imports. Maps component class names to stages.
_STAGE_MAP_BY_NAME: dict[str, str] = {
    "BQQuery": "ingest",
    "BigQueryExtract": "ingest",
    "GCSExtract": "ingest",
    "BQTransform": "transform",
    "WriteFeatures": "write_features",
    "ReadFeatures": "read_features",
    "TrainModel": "train",
    "EvaluateModel": "evaluate",
    "RegisterModel": "register",
    "DeployModel": "deploy",
    "Email": "notify",
}


def _infer_stage(component: BaseComponent) -> str:
    """Infer the pipeline stage from the component's class name."""
    cls_name = type(component).__name__
    return _STAGE_MAP_BY_NAME.get(cls_name, "custom")


class PipelineBuilder:
    """
    Fluent builder for ML pipeline definitions (explicit stage methods).

    Each method adds one or more steps and returns self for chaining.
    Call .build() at the end to produce a PipelineDefinition.

    schedule: any Airflow/cron expression, "@daily", "@once", or None (manual trigger).
    """

    def __init__(
        self,
        name: str,
        schedule: str | None = "@daily",
        description: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self._name = name
        self._schedule = schedule
        self._description = description
        self._tags = tags or []
        self._steps: list[PipelineStep] = []

    def _add(
        self, stage: str, component: BaseComponent, name: str | None = None,
    ) -> PipelineBuilder:
        step_name = name or f"{stage}_{len(self._steps)}"
        task_type = getattr(component, "_task_type", TaskType.ML_TASK)
        self._steps.append(
            PipelineStep(name=step_name, component=component, stage=stage, task_type=task_type)
        )
        return self

    def ingest(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a data ingestion step (BigQueryExtract, GCSExtract, etc.)."""
        return self._add("ingest", component, name)

    def transform(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a data transformation step (BQTransform)."""
        return self._add("transform", component, name)

    def write_features(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a Feature Store write step."""
        return self._add("write_features", component, name)

    def read_features(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a Feature Store read step."""
        return self._add("read_features", component, name)

    def train(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a model training step."""
        return self._add("train", component, name)

    def evaluate(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a model evaluation + gating step."""
        return self._add("evaluate", component, name)

    def deploy(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a model deployment step."""
        return self._add("deploy", component, name)

    def step(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a custom step not covered by the named methods above."""
        return self._add("custom", component, name)

    def build(self) -> PipelineDefinition:
        """Produce the immutable PipelineDefinition."""
        if not self._steps:
            raise ValueError(
                f"Pipeline '{self._name}' has no steps. "
                "Add at least one step before calling .build()."
            )
        return PipelineDefinition(
            name=self._name,
            schedule=self._schedule,
            steps=list(self._steps),
            description=self._description,
            tags=self._tags,
        )


class Pipeline(PipelineBuilder):
    """Unified pipeline builder with automatic stage inference.

    Usage:
        pipeline = (
            Pipeline(name="training", schedule="@daily")
            .add(BQQuery(sql="SELECT ..."))
            .add(TrainModel(), name="Train")
            .add(Email(to=["team@co.com"], subject="Done"))
            .build()
        )

    The .add() method infers the stage from the component type and reads the
    _task_type from the component class (set by @task / @ml_task decorators).
    All PipelineBuilder stage methods (.ingest(), .train(), etc.) remain available.
    """

    def add(self, component: BaseComponent, name: str | None = None) -> Pipeline:
        """Add a component with automatic stage inference.

        The stage is inferred from the component class name via _STAGE_MAP_BY_NAME.
        The task_type is read from the component's _task_type ClassVar.
        """
        stage = _infer_stage(component)
        step_name = name or f"{stage}_{len(self._steps)}"
        task_type = getattr(component, "_task_type", TaskType.ML_TASK)
        self._steps.append(
            PipelineStep(name=step_name, component=component, stage=stage, task_type=task_type)
        )
        return self
