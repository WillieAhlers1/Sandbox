"""Unit tests for PipelineCompiler (gcp_ml_framework.pipeline.compiler)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.pipeline.builder import Pipeline
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
        defn = Pipeline(name="test-pipe").add(comp).build()

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
        defn = Pipeline(name="env-pipe").add(comp).build()

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
        defn = Pipeline(name="train-pipe").add(train, name="train_0").build()

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


# ---------------------------------------------------------------------------
# _build_derived_params: serving image default
# ---------------------------------------------------------------------------


class TestBuildDerivedParamsServingImage:
    """RegisterModel/DeployModel steps get the dedicated serving image, not sklearn."""

    def test_register_model_gets_serving_image(self, mock_context, tmp_path):
        """RegisterModel step uses the dedicated serving image as default."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        reg = RegisterModel(component_name="register_step")
        defn = Pipeline(name="serve-pipe").add(reg, name="register_0").build()

        derived = compiler._build_derived_params(
            mock_context, defn, defn.steps, pipeline_dir=None,
            serving_image="us-central1-docker.pkg.dev/proj/repo/serve-pipe-serving:tag",
        )

        assert "register_0" in derived
        serving = derived["register_0"]["serving_container_image"]
        assert "-serving:" in serving
        assert "sklearn" not in serving

    def test_deploy_model_gets_serving_image(self, mock_context, tmp_path):
        """DeployModel step uses the dedicated serving image as default."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        dep = DeployModel(component_name="deploy_step", endpoint_name="ep")
        defn = Pipeline(name="deploy-pipe").add(dep, name="deploy_0").build()

        derived = compiler._build_derived_params(
            mock_context, defn, defn.steps, pipeline_dir=None,
            serving_image="us-central1-docker.pkg.dev/proj/repo/deploy-pipe-serving:tag",
        )

        assert "deploy_0" in derived
        serving = derived["deploy_0"]["serving_container_image"]
        assert "-serving:" in serving
        assert "sklearn" not in serving

    def test_explicit_serving_image_not_overridden(self, mock_context, tmp_path):
        """If component already sets serving_container_image, compiler does not override."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        reg = RegisterModel(
            component_name="register_step",
            serving_container_image="custom-image:v1",
        )
        defn = Pipeline(name="custom-pipe").add(reg, name="register_0").build()

        derived = compiler._build_derived_params(
            mock_context, defn, defn.steps, pipeline_dir=None,
            serving_image="us-central1-docker.pkg.dev/proj/repo/custom-pipe-serving:tag",
        )

        # When explicit image is set, serving_container_image should NOT appear in derived
        if "register_0" in derived:
            assert "serving_container_image" not in derived["register_0"]
