"""Unit tests for PipelineBuilder (gcp_ml_framework.pipeline.builder)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.pipeline.builder import PipelineBuilder, PipelineDefinition

pytestmark = pytest.mark.unit


class DummyComponent(BaseComponent):
    component_name: str = "dummy"


# ---------------------------------------------------------------------------
# Fluent chaining
# ---------------------------------------------------------------------------


class TestBuilderChaining:
    """PipelineBuilder methods return self so calls can be chained."""

    def test_builder_chaining(self):
        """Every fluent method returns the same PipelineBuilder instance."""
        builder = PipelineBuilder(name="test-pipeline")
        comp = DummyComponent()

        result = (
            builder
            .ingest(comp)
            .transform(comp)
            .train(comp)
            .evaluate(comp)
            .deploy(comp)
            .write_features(comp)
            .read_features(comp)
            .step(comp)
        )
        assert result is builder


# ---------------------------------------------------------------------------
# .build() produces PipelineDefinition
# ---------------------------------------------------------------------------


class TestBuilderBuild:
    """PipelineBuilder.build() returns a PipelineDefinition with the right step count."""

    def test_builder_build_produces_definition(self):
        """Three steps added -> PipelineDefinition with 3 steps."""
        comp = DummyComponent()
        defn = (
            PipelineBuilder(name="my-pipeline", schedule="@daily")
            .ingest(comp)
            .transform(comp)
            .train(comp)
            .build()
        )

        assert isinstance(defn, PipelineDefinition)
        assert defn.name == "my-pipeline"
        assert defn.schedule == "@daily"
        assert len(defn.steps) == 3


# ---------------------------------------------------------------------------
# Empty builder raises
# ---------------------------------------------------------------------------


class TestBuilderEmpty:
    """Building with zero steps is an error."""

    def test_builder_empty_raises(self):
        """build() on an empty builder raises ValueError."""
        builder = PipelineBuilder(name="empty")
        with pytest.raises(ValueError, match="no steps"):
            builder.build()


# ---------------------------------------------------------------------------
# Step stages
# ---------------------------------------------------------------------------


class TestBuilderStepStages:
    """Each fluent method sets the correct stage on the resulting PipelineStep."""

    def test_builder_step_stages(self):
        """ingest -> 'ingest', transform -> 'transform', train -> 'train', etc."""
        comp = DummyComponent()
        defn = (
            PipelineBuilder(name="stages")
            .ingest(comp)
            .transform(comp)
            .write_features(comp)
            .read_features(comp)
            .train(comp)
            .evaluate(comp)
            .deploy(comp)
            .step(comp)
            .build()
        )

        expected_stages = [
            "ingest",
            "transform",
            "write_features",
            "read_features",
            "train",
            "evaluate",
            "deploy",
            "custom",
        ]
        actual_stages = [s.stage for s in defn.steps]
        assert actual_stages == expected_stages


# ---------------------------------------------------------------------------
# Default step names
# ---------------------------------------------------------------------------


class TestBuilderDefaultStepNames:
    """When no explicit name is given, names are '{stage}_{index}'."""

    def test_builder_default_step_names(self):
        """Default names follow the '{stage}_{global_index}' pattern."""
        comp = DummyComponent()
        defn = (
            PipelineBuilder(name="defaults")
            .ingest(comp)
            .transform(comp)
            .train(comp)
            .build()
        )

        assert defn.step_names == ["ingest_0", "transform_1", "train_2"]


# ---------------------------------------------------------------------------
# Custom step names
# ---------------------------------------------------------------------------


class TestBuilderCustomStepNames:
    """Explicit name parameter overrides the default naming."""

    def test_builder_custom_step_names(self):
        """Custom names passed to each method are preserved in the definition."""
        comp = DummyComponent()
        defn = (
            PipelineBuilder(name="custom")
            .ingest(comp, name="my_ingest")
            .train(comp, name="my_train")
            .build()
        )

        assert defn.step_names == ["my_ingest", "my_train"]
