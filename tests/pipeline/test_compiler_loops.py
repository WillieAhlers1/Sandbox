"""Unit tests for loop/condition compilation (REQS 22.0)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline
from gcp_ml_framework.pipeline.smart_compiler import SmartCompiler

pytestmark = pytest.mark.unit


@ml_task
class DummyML(BaseComponent):
    """ML component for compilation tests."""

    brand: str = ""
    component_name: str = "dummy_ml"


@task
class DummyTask(BaseComponent):
    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# SmartCompiler validation
# ---------------------------------------------------------------------------


class TestSmartCompilerValidation:
    def test_rejects_task_in_loop(self, mock_context, tmp_path):
        """SmartCompiler raises NotImplementedError for @task in for_each."""
        # Build a pipeline with a loop containing @task step
        # We bypass the builder validation by constructing directly
        from gcp_ml_framework.pipeline.builder import (
            LoopBlock,
            PipelineDefinition,
            PipelineStep,
        )

        defn = PipelineDefinition(
            name="test",
            schedule=None,
            steps=[],
            loop_blocks=[
                LoopBlock(
                    items=["a", "b"],
                    item_param="brand",
                    steps=[
                        PipelineStep(
                            name="bad_step",
                            component=DummyTask(component_name="bad"),
                            task_type=DummyTask.task_type,
                        ),
                    ],
                    index=0,
                ),
            ],
        )

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        with pytest.raises(NotImplementedError, match="only supports @ml_task"):
            compiler.compile(defn, mock_context)

    def test_rejects_task_in_condition(self, mock_context, tmp_path):
        """SmartCompiler raises NotImplementedError for @task in condition."""
        from gcp_ml_framework.pipeline.builder import (
            ConditionBlock,
            PipelineDefinition,
            PipelineStep,
        )

        defn = PipelineDefinition(
            name="test",
            schedule=None,
            steps=[
                PipelineStep(
                    name="eval",
                    component=DummyML(),
                    task_type=DummyML.task_type,
                ),
            ],
            condition_blocks=[
                ConditionBlock(
                    source_step="eval",
                    then_steps=[
                        PipelineStep(
                            name="bad_cond",
                            component=DummyTask(component_name="bad"),
                            task_type=DummyTask.task_type,
                        ),
                    ],
                ),
            ],
        )

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        with pytest.raises(NotImplementedError, match="only supports @ml_task"):
            compiler.compile(defn, mock_context)

    def test_accepts_ml_task_in_loop(self, mock_context, tmp_path):
        """SmartCompiler does not raise for @ml_task in for_each."""
        defn = (
            Pipeline(name="test_loop", schedule=None)
            .add(DummyML(), name="sequential_step")
            .for_each(items=["a", "b"], steps=[DummyML()], item_param="brand")
            .build()
        )

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        # Should not raise — validation passes
        # Compilation itself may fail (no real images), but validation succeeds
        try:
            compiler.compile(defn, mock_context)
        except NotImplementedError:
            pytest.fail("SmartCompiler rejected @ml_task in for_each")
        except Exception:
            pass  # Other errors (image resolution, etc.) are expected


# ---------------------------------------------------------------------------
# Builder integration — for_each produces valid PipelineDefinition
# ---------------------------------------------------------------------------


class TestLoopBuilderIntegration:
    def test_for_each_builds_with_sequential_steps(self):
        """Pipeline with both sequential and loop steps builds correctly."""
        defn = (
            Pipeline(name="mixed")
            .add(DummyML(), name="step_1")
            .for_each(items=["x", "y"], steps=[DummyML()], item_param="brand")
            .build()
        )
        assert len(defn.steps) == 1
        assert len(defn.loop_blocks) == 1
        assert defn.has_control_flow is True

    def test_condition_builds_with_sequential_steps(self):
        """Pipeline with both sequential and condition steps builds correctly."""
        defn = (
            Pipeline(name="cond")
            .add(DummyML(), name="eval")
            .condition(
                source_step="eval",
                then_steps=[DummyML()],
            )
            .build()
        )
        assert len(defn.steps) == 1
        assert len(defn.condition_blocks) == 1
        assert defn.has_control_flow is True
