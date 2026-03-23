"""Unit tests for Pipeline.for_each() and Pipeline.condition() (REQS 22.0)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@ml_task
class DummyML(BaseComponent):
    """ML component for loop/condition tests."""

    brand: str = ""
    component_name: str = "dummy_ml"


@task
class DummyTask(BaseComponent):
    """Task component — should be rejected by for_each/condition."""

    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# for_each
# ---------------------------------------------------------------------------


class TestForEach:
    def test_for_each_returns_self(self):
        """for_each() returns Pipeline for fluent chaining."""
        p = Pipeline(name="test")
        result = p.for_each(
            items=["a", "b"],
            steps=[DummyML()],
        )
        assert result is p

    def test_for_each_captures_items(self):
        """Loop block stores items and item_param."""
        defn = (
            Pipeline(name="test")
            .for_each(
                items=["brand_a", "brand_b", "brand_c"],
                steps=[DummyML()],
                item_param="brand",
            )
            .build()
        )
        assert len(defn.loop_blocks) == 1
        lb = defn.loop_blocks[0]
        assert lb.items == ["brand_a", "brand_b", "brand_c"]
        assert lb.item_param == "brand"
        assert len(lb.steps) == 1
        assert lb.index == 0

    def test_for_each_rejects_task_components(self):
        """@task components cannot be used in for_each — Airflow can't unroll."""
        with pytest.raises(ValueError, match="only supports @ml_task"):
            Pipeline(name="test").for_each(
                items=["a", "b"],
                steps=[DummyTask(component_name="bad")],
            )

    def test_for_each_accepts_ml_task_components(self):
        """@ml_task components are accepted in for_each."""
        defn = (
            Pipeline(name="test")
            .for_each(
                items=["a", "b"],
                steps=[DummyML()],
            )
            .build()
        )
        assert len(defn.loop_blocks) == 1

    def test_for_each_multiple_loops(self):
        """Multiple for_each calls create multiple loop blocks."""
        defn = (
            Pipeline(name="test")
            .for_each(items=["a"], steps=[DummyML()])
            .for_each(items=["x", "y"], steps=[DummyML()])
            .build()
        )
        assert len(defn.loop_blocks) == 2
        assert defn.loop_blocks[0].index == 0
        assert defn.loop_blocks[1].index == 1

    def test_for_each_default_item_param(self):
        """Default item_param is 'loop_item'."""
        defn = Pipeline(name="test").for_each(items=["a"], steps=[DummyML()]).build()
        assert defn.loop_blocks[0].item_param == "loop_item"


# ---------------------------------------------------------------------------
# condition
# ---------------------------------------------------------------------------


class TestCondition:
    def test_condition_returns_self(self):
        """condition() returns Pipeline for fluent chaining."""
        p = Pipeline(name="test").add(DummyML(), name="train")
        result = p.condition(
            source_step="train",
            then_steps=[DummyML()],
        )
        assert result is p

    def test_condition_captures_source_step(self):
        """Condition block stores source step reference."""
        defn = (
            Pipeline(name="test")
            .add(DummyML(), name="evaluate")
            .condition(
                source_step="evaluate",
                output_key="output_uri",
                operator="!=",
                value="",
                then_steps=[DummyML()],
            )
            .build()
        )
        assert len(defn.condition_blocks) == 1
        cb = defn.condition_blocks[0]
        assert cb.source_step == "evaluate"
        assert cb.output_key == "output_uri"
        assert cb.operator == "!="
        assert cb.value == ""
        assert len(cb.then_steps) == 1

    def test_condition_rejects_task_components(self):
        """@task components cannot be used in condition branches."""
        with pytest.raises(ValueError, match="only supports @ml_task"):
            Pipeline(name="test").add(DummyML(), name="eval").condition(
                source_step="eval",
                then_steps=[DummyTask(component_name="bad")],
            )

    def test_condition_with_else(self):
        """Condition block captures else_steps."""
        defn = (
            Pipeline(name="test")
            .add(DummyML(), name="eval")
            .condition(
                source_step="eval",
                then_steps=[DummyML()],
                else_steps=[DummyML()],
            )
            .build()
        )
        cb = defn.condition_blocks[0]
        assert len(cb.then_steps) == 1
        assert len(cb.else_steps) == 1


# ---------------------------------------------------------------------------
# PipelineDefinition integration
# ---------------------------------------------------------------------------


class TestPipelineDefinitionControlFlow:
    def test_has_control_flow_false_by_default(self):
        """No control flow when only sequential steps."""
        defn = Pipeline(name="test").add(DummyML()).build()
        assert defn.has_control_flow is False

    def test_has_control_flow_with_loop(self):
        """has_control_flow is True when loop blocks present."""
        defn = Pipeline(name="test").for_each(items=["a"], steps=[DummyML()]).build()
        assert defn.has_control_flow is True

    def test_has_control_flow_with_condition(self):
        """has_control_flow is True when condition blocks present."""
        defn = (
            Pipeline(name="test")
            .add(DummyML(), name="eval")
            .condition(source_step="eval", then_steps=[DummyML()])
            .build()
        )
        assert defn.has_control_flow is True

    def test_build_allows_empty_steps_with_control_flow(self):
        """build() allows empty sequential steps if loop_blocks exist."""
        defn = Pipeline(name="test").for_each(items=["a", "b"], steps=[DummyML()]).build()
        assert len(defn.steps) == 0
        assert len(defn.loop_blocks) == 1
