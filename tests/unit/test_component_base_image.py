"""Tests for component-base Docker image and pre-built base image support.

Components should accept an optional base_image parameter in as_kfp_component().
When provided, the component uses the pre-built image and skips packages_to_install.
When omitted, the component falls back to python:3.11-slim + packages_to_install
for backwards compatibility.
"""

from pathlib import Path

from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ingestion.gcs_extract import GCSExtract
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import (
    ReadFeatures,
    WriteFeatures,
)


CUSTOM_BASE_IMAGE = "us-central1-docker.pkg.dev/my-proj/my-repo/component-base:latest"

# Packages that components install at runtime — none should appear when using
# a pre-built component-base image.
_USER_PACKAGES = [
    "google-cloud-bigquery",
    "google-cloud-storage",
    "google-cloud-aiplatform",
    "scikit-learn",
    "pyarrow",
    "pandas",
    "db-dtypes",
]


def _get_kfp_command_str(kfp_fn):
    """Join the KFP container command list into a single string for inspection."""
    return " ".join(str(c) for c in kfp_fn.component_spec.implementation.container.command)


def _get_kfp_image(kfp_fn):
    """Get the base image from a KFP component spec."""
    return kfp_fn.component_spec.implementation.container.image


def _assert_no_user_packages_installed(kfp_fn):
    """Assert that no user-specified packages appear in the pip install command.

    KFP embeds both the pip install command and the Python source code in the
    container command list. We only check the pip install portion (the first
    command element that contains 'pip'), not the source code itself — since
    source code naturally references package modules via ``import``.
    """
    commands = kfp_fn.component_spec.implementation.container.command
    # The first command element with 'pip' contains the install commands
    pip_line = next((str(c) for c in commands if "pip" in str(c)), "")
    for pkg in _USER_PACKAGES:
        assert pkg not in pip_line, f"Package {pkg!r} should not be pip-installed with pre-built image"


# ── Dockerfile ────────────────────────────────────────────────────────────────


class TestComponentBaseDockerfile:
    def test_component_base_dockerfile_exists(self):
        path = Path("docker/base/component-base/Dockerfile")
        assert path.exists(), f"Missing {path}"

    def test_component_base_dockerfile_uses_base_python(self):
        content = Path("docker/base/component-base/Dockerfile").read_text()
        assert "base-python" in content

    def test_component_base_dockerfile_installs_gcp_sdks(self):
        content = Path("docker/base/component-base/Dockerfile").read_text()
        for pkg in [
            "google-cloud-bigquery",
            "google-cloud-storage",
            "google-cloud-aiplatform",
        ]:
            assert pkg in content, f"component-base Dockerfile missing {pkg}"

    def test_component_base_dockerfile_installs_data_packages(self):
        content = Path("docker/base/component-base/Dockerfile").read_text()
        for pkg in ["pyarrow", "pandas"]:
            assert pkg in content, f"component-base Dockerfile missing {pkg}"

    def test_component_base_dockerfile_does_not_install_heavy_ml_packages(self):
        """component-base should NOT include heavy ML libs (that's base-ml's job).
        Note: scikit-learn IS included because EvaluateModel always requires it,
        and VPC SC environments block runtime pip install."""
        content = Path("docker/base/component-base/Dockerfile").read_text()
        for pkg in ["xgboost", "lightgbm"]:
            assert pkg not in content, f"component-base should not include {pkg}"

    def test_component_base_dockerfile_includes_sklearn(self):
        """scikit-learn must be in component-base for EvaluateModel (VPC SC)."""
        content = Path("docker/base/component-base/Dockerfile").read_text()
        assert "scikit-learn" in content


# ── BigQueryExtract ───────────────────────────────────────────────────────────


class TestBigQueryExtractBaseImage:
    def test_default_base_image_unchanged(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        fn = comp.as_kfp_component()
        assert _get_kfp_image(fn) == "python:3.11-slim"

    def test_custom_base_image_used(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)

    def test_has_user_packages_without_custom_base_image(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        fn = comp.as_kfp_component()
        assert "google-cloud-bigquery" in _get_kfp_command_str(fn)


# ── GCSExtract ────────────────────────────────────────────────────────────────


class TestGCSExtractBaseImage:
    def test_custom_base_image_used(self):
        comp = GCSExtract(source_uri="gs://b/p", destination_folder="raw")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = GCSExtract(source_uri="gs://b/p", destination_folder="raw")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── BQTransform ───────────────────────────────────────────────────────────────


class TestBQTransformBaseImage:
    def test_custom_base_image_used(self):
        comp = BQTransform(sql="SELECT 1", output_table="t")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = BQTransform(sql="SELECT 1", output_table="t")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── WriteFeatures ─────────────────────────────────────────────────────────────


class TestWriteFeaturesBaseImage:
    def test_custom_base_image_used(self):
        comp = WriteFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = WriteFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── ReadFeatures ──────────────────────────────────────────────────────────────


class TestReadFeaturesBaseImage:
    def test_custom_base_image_used(self):
        comp = ReadFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = ReadFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── TrainModel ────────────────────────────────────────────────────────────────


class TestTrainModelBaseImage:
    def test_custom_base_image_used(self):
        comp = TrainModel(trainer_image="gcr.io/proj/trainer:latest")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = TrainModel(trainer_image="gcr.io/proj/trainer:latest")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── EvaluateModel ─────────────────────────────────────────────────────────────


class TestEvaluateModelBaseImage:
    def test_custom_base_image_used(self):
        comp = EvaluateModel()
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_gcp_sdk_packages_with_custom_base_image(self):
        """GCP SDK packages should be skipped, but scikit-learn must still be installed."""
        comp = EvaluateModel()
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        commands = fn.component_spec.implementation.container.command
        pip_line = next((str(c) for c in commands if "pip" in str(c)), "")
        # GCP SDKs should NOT be installed (component-base provides them)
        for pkg in ["google-cloud-bigquery", "google-cloud-storage", "google-cloud-aiplatform", "pandas", "db-dtypes"]:
            assert pkg not in pip_line, f"Package {pkg!r} should not be pip-installed with pre-built image"
        # scikit-learn MUST still be installed (not in component-base)
        assert "scikit-learn" in pip_line, "scikit-learn must be installed even with pre-built image"


# ── DeployModel ───────────────────────────────────────────────────────────────


class TestDeployModelBaseImage:
    def test_custom_base_image_used(self):
        comp = DeployModel(endpoint_name="test")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        assert _get_kfp_image(fn) == CUSTOM_BASE_IMAGE

    def test_no_user_packages_with_custom_base_image(self):
        comp = DeployModel(endpoint_name="test")
        fn = comp.as_kfp_component(base_image=CUSTOM_BASE_IMAGE)
        _assert_no_user_packages_installed(fn)


# ── Compiler integration ─────────────────────────────────────────────────────


class TestCompilerComponentBaseImage:
    def test_compiled_yaml_uses_component_base_image(self, test_context, tmp_path):
        """Compiled pipeline YAML should reference component-base, not python:3.11-slim."""
        from gcp_ml_framework.pipeline.builder import PipelineBuilder
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline_def = (
            PipelineBuilder(name="test-base-image", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .build()
        )
        compiler = PipelineCompiler(output_dir=tmp_path)
        output = compiler.compile(pipeline_def, test_context)
        yaml_content = output.read_text()
        assert "python:3.11-slim" not in yaml_content
        assert "component-base" in yaml_content

    def test_compiled_yaml_no_user_package_installs(self, test_context, tmp_path):
        """Compiled pipeline YAML should not pip-install user packages."""
        from gcp_ml_framework.pipeline.builder import PipelineBuilder
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline_def = (
            PipelineBuilder(name="test-no-pip", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .transform(BQTransform(sql="SELECT 1", output_table="xform"))
            .build()
        )
        compiler = PipelineCompiler(output_dir=tmp_path)
        output = compiler.compile(pipeline_def, test_context)
        yaml_content = output.read_text()
        for pkg in _USER_PACKAGES:
            assert pkg not in yaml_content, f"YAML should not pip-install {pkg!r}"


# ── Docker build script ──────────────────────────────────────────────────────


class TestDockerBuildComponentBase:
    def test_docker_build_script_references_component_base(self):
        content = Path("scripts/docker_build.sh").read_text()
        assert "component-base" in content
