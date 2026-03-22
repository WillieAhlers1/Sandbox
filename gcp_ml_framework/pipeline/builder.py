"""
Pipeline — fluent builder for ML pipeline definitions.

A data scientist edits exactly one file (pipeline.py) to define their pipeline.
No KFP YAML, no Airflow DAG code, no operator wiring.

Usage:
    pipeline = (
        Pipeline(name="churn-prediction", schedule="0 6 * * 1")
        .add(BQQuery(sql="SELECT ..."))
        .add(TrainModel(machine_type="n2-standard-8"), name="Train Churn Model")
        .add(Email(to=["team@co.com"], subject="Done"))
        .build()
    )
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.types import TaskType


class PipelineStep(BaseModel):
    """A single step in the pipeline, wrapping a component."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    component: BaseComponent
    task_type: TaskType = TaskType.ML_TASK


class PipelineDefinition(BaseModel):
    """
    The compiled pipeline definition produced by Pipeline.build().

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


class Pipeline:
    """Unified pipeline builder. A pipeline is an ordered sequence of steps.

    Usage:
        pipeline = (
            Pipeline(name="training", schedule="@daily")
            .add(BQQuery(sql="SELECT ..."), name="Ingest")
            .add(TrainModel(), name="Train")
            .add(Email(to=["team@co.com"]), name="Notify")
            .build()
        )
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

    def add(
        self, component: BaseComponent, name: str | None = None,
    ) -> Pipeline:
        """Add a component to the pipeline.

        The task_type is read from the component's task_type ClassVar
        (set by @task or @ml_task decorator).
        """
        step_name = name or f"{type(component).__name__}_{len(self._steps)}"
        task_type = getattr(component, "task_type", TaskType.ML_TASK)
        self._steps.append(
            PipelineStep(
                name=step_name, component=component, task_type=task_type,
            )
        )
        return self

    def build(self) -> PipelineDefinition:
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
