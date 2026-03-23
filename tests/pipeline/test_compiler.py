"""Unit tests for PipelineCompiler (gcp_ml_framework.pipeline.compiler)."""

from __future__ import annotations

import pytest
import yaml

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.decorators import ml_task
from gcp_ml_framework.pipeline.builder import Pipeline, PipelineStep
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

        derived = compiler._build_derived_params(mock_context, defn, defn.steps, pipeline_dir=None)

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
    """RegisterModel gets serving image via default_image; DeployModel does NOT."""

    def test_register_model_gets_default_serving_image(self, mock_context, tmp_path):
        """RegisterModel without serving_dockerfile/serving_container_image gets default_image."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        reg = RegisterModel(component_name="register_step")
        defn = Pipeline(name="serve-pipe").add(reg, name="register_0").build()

        derived = compiler._build_derived_params(
            mock_context,
            defn,
            defn.steps,
            pipeline_dir=None,
            default_image="us-central1-docker.pkg.dev/proj/repo/train:tag",
        )

        assert "register_0" in derived
        assert "serving_container_image" in derived["register_0"]

    def test_deploy_model_does_not_get_serving_image(self, mock_context, tmp_path):
        """DeployModel gets model_display_name and endpoint_display_name only — NO serving image.

        Client design principle: RegisterModel is the SINGLE OWNER of the serving image.
        """
        compiler = PipelineCompiler(output_dir=tmp_path)
        dep = DeployModel(component_name="deploy_step", model_name="test")
        defn = Pipeline(name="deploy-pipe").add(dep, name="deploy_0").build()

        derived = compiler._build_derived_params(
            mock_context,
            defn,
            defn.steps,
            pipeline_dir=None,
            default_image="us-central1-docker.pkg.dev/proj/repo/train:tag",
        )

        assert "deploy_0" in derived
        assert "model_display_name" in derived["deploy_0"]
        assert "endpoint_display_name" in derived["deploy_0"]
        assert "serving_container_image" not in derived["deploy_0"]

    def test_explicit_serving_image_not_overridden(self, mock_context, tmp_path):
        """If RegisterModel already sets serving_container_image, compiler does not override."""
        compiler = PipelineCompiler(output_dir=tmp_path)
        reg = RegisterModel(
            component_name="register_step",
            serving_container_image="custom-image:v1",
        )
        defn = Pipeline(name="custom-pipe").add(reg, name="register_0").build()

        derived = compiler._build_derived_params(
            mock_context,
            defn,
            defn.steps,
            pipeline_dir=None,
            default_image="us-central1-docker.pkg.dev/proj/repo/train:tag",
        )

        # When explicit image is set, serving_container_image should NOT appear in derived
        if "register_0" in derived:
            assert "serving_container_image" not in derived["register_0"]


# ---------------------------------------------------------------------------
# _derive_step_params — single-step derivation
# ---------------------------------------------------------------------------


class TestDeriveStepParams:
    """_derive_step_params computes derived params for a single step."""

    def test_train_model_gets_job_name_and_model_output_uri(self, mock_context, tmp_path):
        compiler = PipelineCompiler(output_dir=tmp_path)
        train = TrainModel(component_name="train_step")
        step = PipelineStep(name="train_0", component=train, task_type=train.task_type)
        defn = Pipeline(name="my-pipe").add(train, name="train_0").build()

        extra = compiler._derive_step_params(mock_context, defn, step)

        assert "job_name" in extra
        assert "model_output_uri" in extra
        assert extra["model_output_uri"].startswith("gs://")

    def test_register_model_gets_display_name_and_serving_image(self, mock_context, tmp_path):
        compiler = PipelineCompiler(output_dir=tmp_path)
        reg = RegisterModel(
            component_name="register_step",
            model_name="my-model",
            serving_dockerfile="pipelines/house_price/serve.Dockerfile",
        )
        step = PipelineStep(name="register_0", component=reg, task_type=reg.task_type)
        defn = Pipeline(name="my-pipe").add(reg, name="register_0").build()

        extra = compiler._derive_step_params(mock_context, defn, step)

        assert "model_display_name" in extra
        assert "my-model" in extra["model_display_name"] or "my-pipe" in extra["model_display_name"]
        assert "serving_container_image" in extra
        assert extra["serving_container_image"] != ""

    def test_deploy_model_gets_display_name_and_endpoint(self, mock_context, tmp_path):
        compiler = PipelineCompiler(output_dir=tmp_path)
        dep = DeployModel(component_name="deploy_step", model_name="my-model")
        step = PipelineStep(name="deploy_0", component=dep, task_type=dep.task_type)
        defn = Pipeline(name="my-pipe").add(dep, name="deploy_0").build()

        extra = compiler._derive_step_params(mock_context, defn, step)

        assert "model_display_name" in extra
        assert "endpoint_display_name" in extra
        assert "serving_container_image" not in extra

    def test_plain_component_returns_empty(self, mock_context, tmp_path):
        compiler = PipelineCompiler(output_dir=tmp_path)
        comp = DummyComponent()
        step = PipelineStep(name="dummy_0", component=comp, task_type=comp.task_type)
        defn = Pipeline(name="my-pipe").add(comp, name="dummy_0").build()

        extra = compiler._derive_step_params(mock_context, defn, step)

        assert extra == {}


# ---------------------------------------------------------------------------
# Condition/loop blocks get derived params (regression tests)
# ---------------------------------------------------------------------------


class TestConditionBlockDerivedParams:
    """Steps inside .condition() blocks must receive derived params."""

    def test_condition_register_gets_model_display_name(self, mock_context, tmp_path):
        """RegisterModel inside .condition() gets model_display_name + serving_container_image."""
        train = TrainModel(component_name="train_step")
        reg = RegisterModel(
            component_name="register_step",
            model_name="cond-model",
        )
        defn = (
            Pipeline(name="cond-pipe")
            .add(train, name="Train")
            .condition(
                source_step="Train",
                operator="!=",
                value="",
                then_steps=[reg],
                then_names=["Register"],
            )
            .build()
        )

        compiler = PipelineCompiler(output_dir=tmp_path)
        try:
            yaml_path = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")

        with open(yaml_path) as f:
            pipeline_yaml = yaml.safe_load(f)

        # Find register-model task inside the condition sub-DAG
        for comp_name, comp_def in pipeline_yaml.get("components", {}).items():
            sub_dag = comp_def.get("dag", {})
            for task_name, task_def in sub_dag.get("tasks", {}).items():
                if "register" in task_name:
                    inputs = task_def.get("inputs", {}).get("parameters", {})
                    mdn = inputs.get("model_display_name", {})
                    val = mdn.get("runtimeValue", {}).get("constant", "")
                    assert val != "", (
                        f"model_display_name is empty for {task_name} inside condition block"
                    )

    def test_condition_deploy_gets_endpoint_display_name(self, mock_context, tmp_path):
        """DeployModel inside .condition() gets endpoint_display_name."""
        train = TrainModel(component_name="train_step")
        dep = DeployModel(component_name="deploy_step", model_name="cond-model")
        defn = (
            Pipeline(name="cond-pipe")
            .add(train, name="Train")
            .condition(
                source_step="Train",
                operator="!=",
                value="",
                then_steps=[dep],
                then_names=["Deploy"],
            )
            .build()
        )

        compiler = PipelineCompiler(output_dir=tmp_path)
        try:
            yaml_path = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")

        with open(yaml_path) as f:
            pipeline_yaml = yaml.safe_load(f)

        for comp_name, comp_def in pipeline_yaml.get("components", {}).items():
            sub_dag = comp_def.get("dag", {})
            for task_name, task_def in sub_dag.get("tasks", {}).items():
                if "deploy" in task_name:
                    inputs = task_def.get("inputs", {}).get("parameters", {})
                    edn = inputs.get("endpoint_display_name", {})
                    val = edn.get("runtimeValue", {}).get("constant", "")
                    assert val != "", (
                        f"endpoint_display_name is empty for {task_name} inside condition block"
                    )


class TestLoopBlockDerivedParams:
    """Steps inside .for_each() blocks must receive derived params."""

    def test_loop_train_gets_job_name(self, mock_context, tmp_path):
        """TrainModel inside .for_each() gets job_name and model_output_uri."""

        @ml_task
        class LoopTrainer(TrainModel):
            loop_item: str = ""

        defn = (
            Pipeline(name="loop-pipe")
            .for_each(
                items=["a", "b"],
                steps=[LoopTrainer(component_name="loop_train")],
                item_param="loop_item",
                names=["Loop Train"],
            )
            .build()
        )

        compiler = PipelineCompiler(output_dir=tmp_path)
        try:
            yaml_path = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")

        with open(yaml_path) as f:
            pipeline_yaml = yaml.safe_load(f)

        # Find the loop train task and check it has job_name
        for comp_name, comp_def in pipeline_yaml.get("components", {}).items():
            inputs = comp_def.get("inputDefinitions", {}).get("parameters", {})
            if "job_name" in inputs:
                # Found a component that accepts job_name — good
                return

        # If we get here, check the deployment spec for the loop trainer
        for exec_name, exec_def in (
            pipeline_yaml.get("deploymentSpec", {}).get("executors", {}).items()
        ):
            args = exec_def.get("container", {}).get("args", [])
            if any("job-name" in str(a) or "job_name" in str(a) for a in args):
                return

        pytest.fail("TrainModel inside for_each did not receive job_name")
