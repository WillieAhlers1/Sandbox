"""Unit tests for training pipeline steps."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
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
