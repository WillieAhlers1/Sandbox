"""
PipelineBuilder — fluent DSL for defining ML pipelines.

A data scientist edits exactly one file (pipeline.py) to define their pipeline.
No KFP YAML, no Airflow DAG code, no operator wiring.

Usage:
    pipeline = (
        PipelineBuilder(name="churn-prediction", schedule="0 6 * * 1")
        .ingest(BigQueryExtract(...))
        .transform(BQTransform(...))
        .write_features(WriteFeatures(...))
        .train(TrainModel(...))
        .evaluate(EvaluateModel(...))
        .deploy(DeployModel(...))
        .build()
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.components.base import BaseComponent


@dataclass
class PipelineStep:
    """A single step in the pipeline, wrapping a component and its position."""

    name: str
    component: "BaseComponent"
    stage: str  # 'ingest' | 'transform' | 'write_features' | 'train' | 'evaluate' | 'deploy'


@dataclass
class PipelineDefinition:
    """
    The compiled pipeline definition produced by PipelineBuilder.build().

    This is the object passed to:
    - PipelineCompiler (→ KFP YAML for Vertex AI)
    - LocalRunner (→ sequential local execution)
    - DAGFactory (→ Airflow DAG)
    """

    name: str
    schedule: str | None
    steps: list[PipelineStep] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]


class PipelineBuilder:
    """
    Fluent builder for ML pipeline definitions.

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

    def _add(self, stage: str, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        step_name = name or f"{stage}_{len(self._steps)}"
        self._steps.append(PipelineStep(name=step_name, component=component, stage=stage))
        return self

    def ingest(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a data ingestion step (BigQueryExtract, GCSExtract, etc.)."""
        return self._add("ingest", component, name)

    def transform(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a data transformation step (BQTransform, PandasTransform)."""
        return self._add("transform", component, name)

    def write_features(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a Feature Store write step."""
        return self._add("write_features", component, name)

    def read_features(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a Feature Store read step."""
        return self._add("read_features", component, name)

    def train(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a model training step."""
        return self._add("train", component, name)

    def evaluate(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a model evaluation + gating step."""
        return self._add("evaluate", component, name)

    def deploy(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a model deployment step."""
        return self._add("deploy", component, name)

    def step(self, component: "BaseComponent", name: str | None = None) -> "PipelineBuilder":
        """Add a custom step not covered by the named methods above."""
        return self._add("custom", component, name)

    def build(self) -> PipelineDefinition:
        """Produce the immutable PipelineDefinition."""
        if not self._steps:
            raise ValueError(f"Pipeline '{self._name}' has no steps. Add at least one step before calling .build().")
        return PipelineDefinition(
            name=self._name,
            schedule=self._schedule,
            steps=list(self._steps),
            description=self._description,
            tags=self._tags,
        )
