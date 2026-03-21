"""Unit tests for PipelineCompiler (gcp_ml_framework.pipeline.compiler)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.pipeline.compiler import PipelineCompiler

pytestmark = pytest.mark.unit


class DummyComponent(BaseComponent):
    component_name: str = "dummy"


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


class TestCompilerImport:
    """Verify the compiler module is importable without side effects."""

    def test_compiler_import(self):
        """PipelineCompiler can be imported and instantiated."""
        compiler = PipelineCompiler(output_dir="/tmp/test_compiler_output")
        assert compiler is not None


# ---------------------------------------------------------------------------
# _build_context_params keys
# ---------------------------------------------------------------------------


class TestBuildContextParamsKeys:
    """_build_context_params returns a dict with all expected keys."""

    def test_build_context_params_keys(self, mock_context, tmp_path):
        """Returned dict contains project, region, environment, and other context keys."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        comp = DummyComponent()
        defn = PipelineBuilder(name="test-pipe").ingest(comp).build()

        params = compiler._build_context_params(mock_context, defn)

        expected_keys = {
            "project",
            "region",
            "project_name",
            "branch",
            "environment",
            "dataset",
            "gcs_prefix",
            "feature_store_id",
            "staging_bucket",
            "experiment_name",
            "artifact_registry",
        }
        assert expected_keys.issubset(params.keys()), (
            f"Missing keys: {expected_keys - params.keys()}"
        )


# ---------------------------------------------------------------------------
# _build_context_params uses context.environment.value
# ---------------------------------------------------------------------------


class TestBuildContextParamsEnvironment:
    """The 'environment' param is sourced from context.environment.value (not git_state)."""

    def test_build_context_params_environment(self, mock_context, tmp_path):
        """environment value matches context.environment.value."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        comp = DummyComponent()
        defn = PipelineBuilder(name="env-pipe").ingest(comp).build()

        params = compiler._build_context_params(mock_context, defn)

        assert params["environment"] == mock_context.environment.value
        assert params["environment"] == "dev"


# ---------------------------------------------------------------------------
# _build_derived_params for TrainModel
# ---------------------------------------------------------------------------


class TestBuildDerivedParamsTrain:
    """TrainModel steps receive job_name and model_output_uri in derived params."""

    def test_build_derived_params_train_model(self, mock_context, tmp_path):
        """TrainModel step gets job_name and model_output_uri from derived params."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        train = TrainModel(component_name="train_step")
        defn = PipelineBuilder(name="train-pipe").train(train, name="train_0").build()

        derived = compiler._build_derived_params(
            mock_context, defn, defn.steps, pipeline_dir=None
        )

        assert "train_0" in derived
        step_params = derived["train_0"]
        assert "job_name" in step_params
        assert "model_output_uri" in step_params
        # Values should be derived from naming convention
        assert "train-pipe" in step_params["job_name"] or "train" in step_params["job_name"]
        assert step_params["model_output_uri"].startswith("gs://")
