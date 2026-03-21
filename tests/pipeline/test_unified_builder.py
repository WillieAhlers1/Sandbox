"""Unit tests for Pipeline unified builder (gcp_ml_framework.pipeline.builder.Pipeline)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType, task
from gcp_ml_framework.pipeline.builder import Pipeline

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyMLComponent(BaseComponent):
    """Inherits default ML_TASK from BaseComponent."""
    component_name: str = "dummy_ml"


@task
class DummyTaskComponent(BaseComponent):
    """Explicitly marked as @task."""
    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# Pipeline.add() with stage inference
# ---------------------------------------------------------------------------


class TestPipelineAdd:
    def test_add_returns_self(self):
        p = Pipeline(name="test")
        result = p.add(DummyMLComponent())
        assert result is p

    def test_add_infers_stage_for_known_components(self):
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel
        from gcp_ml_framework.components.ml.train import TrainModel

        defn = (
            Pipeline(name="test")
            .add(TrainModel(component_name="train"))
            .add(EvaluateModel(component_name="eval"))
            .build()
        )
        assert defn.steps[0].stage == "train"
        assert defn.steps[1].stage == "evaluate"

    def test_add_infers_custom_for_unknown_components(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .build()
        )
        assert defn.steps[0].stage == "custom"

    def test_add_custom_name(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent(), name="My Custom Step")
            .build()
        )
        assert defn.step_names == ["My Custom Step"]

    def test_add_default_name(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .build()
        )
        assert defn.step_names == ["custom_0"]


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
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .add(DummyMLComponent())
            .build()
        )
        assert defn.has_mixed_types is False


# ---------------------------------------------------------------------------
# ML task groups
# ---------------------------------------------------------------------------


class TestMLTaskGroups:
    def test_ml_task_groups_single(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .add(DummyMLComponent())
            .build()
        )
        groups = defn.ml_task_groups
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_ml_task_groups_split_by_task(self):
        """TASK step in the middle splits ML_TASK steps into two groups."""
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .add(DummyTaskComponent(component_name="t"))
            .add(DummyMLComponent())
            .build()
        )
        groups = defn.ml_task_groups
        assert len(groups) == 2
        assert len(groups[0]) == 1
        assert len(groups[1]) == 1

    def test_ml_task_groups_pure_task(self):
        """Pure @task pipeline has zero ML groups."""
        defn = (
            Pipeline(name="test")
            .add(DummyTaskComponent(component_name="t1"))
            .add(DummyTaskComponent(component_name="t2"))
            .build()
        )
        assert defn.ml_task_groups == []


# ---------------------------------------------------------------------------
# Pipeline inherits PipelineBuilder
# ---------------------------------------------------------------------------


class TestPipelineInheritance:
    def test_pipeline_has_stage_methods(self):
        """Pipeline inherits all PipelineBuilder stage methods."""
        p = Pipeline(name="test")
        assert hasattr(p, "ingest")
        assert hasattr(p, "train")
        assert hasattr(p, "deploy")

    def test_pipeline_build_empty_raises(self):
        with pytest.raises(ValueError, match="no steps"):
            Pipeline(name="empty").build()
