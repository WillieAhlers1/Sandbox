"""Unit tests for training pipeline steps and definition."""

from __future__ import annotations

import subprocess
import sys

import pytest

from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestTrainHouseModelStep:
    def test_instantiation(self):
        """HouseTrainModelStep can be instantiated with minimal args."""
        from pipelines.training_pipeline.steps.train_house_model import (
            HouseTrainModelStep,
        )

        step = HouseTrainModelStep(component_name="train_house_model")
        assert step.component_name == "train_house_model"

    def test_has_dataset_field(self, mock_context):
        """dataset field exists and compiler context params populate it."""
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler
        from pipelines.training_pipeline.steps.train_house_model import (
            HouseTrainModelStep,
        )

        step = HouseTrainModelStep(component_name="train_house_model")
        assert hasattr(step, "dataset")

        # Verify compiler passes dataset in context params
        compiler = PipelineCompiler()
        from pipelines.training_pipeline.pipeline import pipeline as pipeline_def

        ctx_params = compiler._build_context_params(mock_context, pipeline_def)
        assert "dataset" in ctx_params
        assert ctx_params["dataset"] == mock_context.bq_dataset

    def test_sql_uses_dataset_template(self):
        """SQL file uses {dataset} placeholder, not a hardcoded dataset name."""
        from importlib.resources import files

        sql = (
            files("pipelines.training_pipeline.sql")
            .joinpath("training_pipeline_features.sql")
            .read_text()
        )
        assert "{dataset}" in sql
        assert "demo_housing_data" not in sql

    def test_step_cli_help(self):
        """Step module responds to --help without error."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pipelines.training_pipeline.steps.train_house_model",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "--dataset" in result.stdout


class TestHouseEvaluateStep:
    """Verify training pipeline evaluation step."""

    def test_instantiation(self):
        """HouseEvaluateStep can be instantiated with default fields."""
        from pipelines.training_pipeline.steps.evaluate_house_model import (
            HouseEvaluateStep,
        )

        step = HouseEvaluateStep()
        assert step.component_name == "evaluate_house_model"

    def test_is_evaluate_model_subclass(self):
        """HouseEvaluateStep inherits from EvaluateModel."""
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel
        from pipelines.training_pipeline.steps.evaluate_house_model import (
            HouseEvaluateStep,
        )

        assert issubclass(HouseEvaluateStep, EvaluateModel)


class TestTrainingPipelineDefinition:
    """Verify the training pipeline has 6 steps with correct types."""

    def test_step_count(self):
        from pipelines.training_pipeline.pipeline import pipeline

        assert len(pipeline.steps) == 6

    def test_step_names(self):
        from pipelines.training_pipeline.pipeline import pipeline

        assert pipeline.step_names == [
            "Ingest Raw Data",
            "Transform Features",
            "Train Model",
            "Evaluate Model",
            "Register Model",
            "Deploy Model",
        ]

    def test_mixed_types(self):
        from pipelines.training_pipeline.pipeline import pipeline

        assert pipeline.has_mixed_types is True

    def test_task_types(self):
        from pipelines.training_pipeline.pipeline import pipeline

        types = [s.task_type for s in pipeline.steps]
        assert types == [
            TaskType.TASK,
            TaskType.TASK,
            TaskType.ML_TASK,
            TaskType.ML_TASK,
            TaskType.ML_TASK,
            TaskType.ML_TASK,
        ]
