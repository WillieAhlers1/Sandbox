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

Loop/Condition (REQS 22.0):
    pipeline = (
        Pipeline(name="multi-brand")
        .for_each(
            items=["brand_a", "brand_b"],
            steps=[BrandTrainer(component_name="train")],
            item_param="brand",
        )
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


class LoopBlock(BaseModel):
    """A for_each loop over items (REQS 22.0).

    Each item is passed to the loop steps via the ``item_param`` field.
    Only @ml_task components are supported — Airflow operators cannot be
    dynamically unrolled at compile time.
    """

    model_config = {"arbitrary_types_allowed": True}

    items: list[str]
    item_param: str
    steps: list[PipelineStep]
    index: int


class ConditionBlock(BaseModel):
    """A conditional block with then/else branches (REQS 22.0).

    Checks a prior step's output and executes then_steps (or else_steps)
    based on the comparison result. Only @ml_task components supported.
    """

    model_config = {"arbitrary_types_allowed": True}

    source_step: str
    output_key: str = "output_uri"
    operator: str = "!="
    value: str = ""
    then_steps: list[PipelineStep] = Field(default_factory=list)
    else_steps: list[PipelineStep] = Field(default_factory=list)
    index: int = 0


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
    loop_blocks: list[LoopBlock] = Field(default_factory=list)
    condition_blocks: list[ConditionBlock] = Field(default_factory=list)
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def step_names(self) -> list[str]:
        """Ordered list of step names in the pipeline."""
        return [s.name for s in self.steps]

    @property
    def has_mixed_types(self) -> bool:
        """True if the pipeline contains both @task and @ml_task steps."""
        types = {s.task_type for s in self.steps}
        return len(types) > 1

    @property
    def has_control_flow(self) -> bool:
        """True if the pipeline uses for_each or condition blocks."""
        return bool(self.loop_blocks or self.condition_blocks)


def _validate_ml_only(
    components: list[BaseComponent],
    context: str,
) -> None:
    """Raise ValueError if any component is @task (not @ml_task)."""
    for comp in components:
        task_type = getattr(comp, "task_type", TaskType.ML_TASK)
        if task_type != TaskType.ML_TASK:
            raise ValueError(
                f"{context} only supports @ml_task components. "
                f"'{type(comp).__name__}' is @task — Airflow operators "
                f"cannot be dynamically unrolled at compile time."
            )


def _make_steps(
    components: list[BaseComponent],
    names: list[str] | None,
    prefix: str,
) -> list[PipelineStep]:
    """Convert a list of components to PipelineSteps with auto-generated names."""
    result = []
    for i, comp in enumerate(components):
        step_name = names[i] if names and i < len(names) else f"{prefix}_{type(comp).__name__}_{i}"
        task_type = getattr(comp, "task_type", TaskType.ML_TASK)
        result.append(PipelineStep(name=step_name, component=comp, task_type=task_type))
    return result


class Pipeline:
    """Unified pipeline builder. A pipeline is an ordered sequence of steps.

    Supports sequential steps (.add), loops (.for_each), and
    conditionals (.condition). Loops and conditions only work with
    @ml_task components.

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
        self._loop_blocks: list[LoopBlock] = []
        self._condition_blocks: list[ConditionBlock] = []

    def add(
        self,
        component: BaseComponent,
        name: str | None = None,
    ) -> Pipeline:
        """Add a component to the pipeline.

        The task_type is read from the component's task_type ClassVar
        (set by @task or @ml_task decorator).
        """
        step_name = name or f"{type(component).__name__}_{len(self._steps)}"
        task_type = getattr(component, "task_type", TaskType.ML_TASK)
        self._steps.append(
            PipelineStep(
                name=step_name,
                component=component,
                task_type=task_type,
            )
        )
        return self

    def for_each(
        self,
        items: list[str],
        steps: list[BaseComponent],
        *,
        item_param: str = "loop_item",
        names: list[str] | None = None,
    ) -> Pipeline:
        """Loop over items, running steps for each.

        Each step component must be @ml_task. @task steps (Airflow operators)
        cannot be dynamically unrolled at compile time.

        Args:
            items: List of string items to iterate over.
            steps: Components to run for each item.
            item_param: Name of the component field that receives the
                loop variable. The data scientist must declare this field
                on their component subclass.
            names: Optional step names (auto-generated if not provided).

        Example::

            @ml_task
            class BrandTrainer(TrainModel):
                brand: str = ""

            pipeline = (
                Pipeline(name="multi_brand")
                .for_each(
                    items=["brand_a", "brand_b"],
                    steps=[BrandTrainer(component_name="train")],
                    item_param="brand",
                )
                .build()
            )
        """
        _validate_ml_only(steps, "for_each()")
        prefix = f"loop_{len(self._loop_blocks)}"
        pipeline_steps = _make_steps(steps, names, prefix)

        self._loop_blocks.append(
            LoopBlock(
                items=items,
                item_param=item_param,
                steps=pipeline_steps,
                index=len(self._loop_blocks),
            )
        )
        return self

    def condition(
        self,
        *,
        source_step: str,
        output_key: str = "output_uri",
        operator: str = "!=",
        value: str = "",
        then_steps: list[BaseComponent],
        else_steps: list[BaseComponent] | None = None,
        then_names: list[str] | None = None,
        else_names: list[str] | None = None,
    ) -> Pipeline:
        """Conditional execution based on a prior step's output.

        Only @ml_task steps are supported in then/else branches.

        Args:
            source_step: Name of the step whose output to check.
            output_key: KFP output key to check (default: "output_uri").
            operator: Comparison operator ("==", "!=", ">", "<", ">=", "<=").
            value: Value to compare against.
            then_steps: Components to run if condition is true.
            else_steps: Components to run if condition is false (optional).
            then_names: Optional names for then_steps.
            else_names: Optional names for else_steps.
        """
        _validate_ml_only(then_steps, "condition()")
        if else_steps:
            _validate_ml_only(else_steps, "condition()")

        idx = len(self._condition_blocks)
        then_pipeline_steps = _make_steps(then_steps, then_names, f"cond_{idx}_then")
        else_pipeline_steps = (
            _make_steps(else_steps, else_names, f"cond_{idx}_else") if else_steps else []
        )

        self._condition_blocks.append(
            ConditionBlock(
                source_step=source_step,
                output_key=output_key,
                operator=operator,
                value=value,
                then_steps=then_pipeline_steps,
                else_steps=else_pipeline_steps,
                index=idx,
            )
        )
        return self

    def build(self) -> PipelineDefinition:
        """Finalize and return the pipeline definition.

        Returns:
            A frozen PipelineDefinition ready for compilation or local execution.

        Raises:
            ValueError: If no steps, loops, or conditions have been added.
        """
        if not self._steps and not self._loop_blocks and not self._condition_blocks:
            raise ValueError(
                f"Pipeline '{self._name}' has no steps. "
                "Add at least one step, for_each, or condition before calling .build()."
            )
        return PipelineDefinition(
            name=self._name,
            schedule=self._schedule,
            steps=list(self._steps),
            loop_blocks=list(self._loop_blocks),
            condition_blocks=list(self._condition_blocks),
            description=self._description,
            tags=self._tags,
        )
