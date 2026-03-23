"""Unit tests for Pipeline builder (gcp_ml_framework.pipeline.builder.Pipeline)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType, ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@ml_task
class DummyMLComponent(BaseComponent):
    """Explicitly marked as @ml_task."""

    component_name: str = "dummy_ml"


@task
class DummyTaskComponent(BaseComponent):
    """Explicitly marked as @task."""

    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# Pipeline.add()
# ---------------------------------------------------------------------------


class TestPipelineAdd:
    def test_add_returns_self(self):
        p = Pipeline(name="test")
        result = p.add(DummyMLComponent())
        assert result is p

    def test_add_custom_name(self):
        defn = Pipeline(name="test").add(DummyMLComponent(), name="My Custom Step").build()
        assert defn.step_names == ["My Custom Step"]

    def test_add_default_name_uses_class_name(self):
        defn = Pipeline(name="test").add(DummyMLComponent()).build()
        assert defn.step_names == ["DummyMLComponent_0"]

    def test_multiple_default_names(self):
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        defn = Pipeline(name="test").add(BQQuery(sql="SELECT 1")).add(DummyMLComponent()).build()
        assert defn.step_names == ["BQQuery_0", "DummyMLComponent_1"]


# ---------------------------------------------------------------------------
# Task type propagation
# ---------------------------------------------------------------------------


class TestPipelineTaskTypes:
    def test_task_type_propagated_from_decorator(self):
        defn = (
            Pipeline(name="test")
            .add(DummyTaskComponent(component_name="t"))
            .add(DummyMLComponent())
            .build()
        )
        assert defn.steps[0].task_type == TaskType.TASK
        assert defn.steps[1].task_type == TaskType.ML_TASK

    def test_has_mixed_types_true(self):
        defn = (
            Pipeline(name="test")
            .add(DummyTaskComponent(component_name="t"))
            .add(DummyMLComponent())
            .build()
        )
        assert defn.has_mixed_types is True

    def test_has_mixed_types_false(self):
        defn = Pipeline(name="test").add(DummyMLComponent()).add(DummyMLComponent()).build()
        assert defn.has_mixed_types is False


# ---------------------------------------------------------------------------
# Pipeline.build()
# ---------------------------------------------------------------------------


class TestPipelineBuild:
    def test_build_empty_raises(self):
        with pytest.raises(ValueError, match="no steps"):
            Pipeline(name="empty").build()

    def test_build_produces_definition(self):
        defn = (
            Pipeline(name="my-pipeline", schedule="@daily")
            .add(DummyMLComponent())
            .add(DummyMLComponent())
            .build()
        )
        assert defn.name == "my-pipeline"
        assert defn.schedule == "@daily"
        assert len(defn.steps) == 2

    def test_step_names_property(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent(), name="a")
            .add(DummyTaskComponent(component_name="t"), name="b")
            .build()
        )
        assert defn.step_names == ["a", "b"]


# ---------------------------------------------------------------------------
# PipelineStep has no stage field
# ---------------------------------------------------------------------------


class TestPipelineStepNoStage:
    def test_step_has_no_stage(self):
        defn = Pipeline(name="test").add(DummyMLComponent()).build()
        assert not hasattr(defn.steps[0], "stage")


# ---------------------------------------------------------------------------
# PipelineBuilder is removed
# ---------------------------------------------------------------------------


class TestPipelineBuilderRemoved:
    def test_pipeline_builder_not_importable(self):
        with pytest.raises(ImportError):
            from gcp_ml_framework.pipeline.builder import PipelineBuilder  # noqa: F401
