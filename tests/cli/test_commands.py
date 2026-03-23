"""Unit tests for CLI module imports (smoke tests)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CLI module import
# ---------------------------------------------------------------------------


class TestCLIModuleImports:
    """Verify the CLI module import chain works without errors."""

    def test_cli_module_imports(self):
        """'from gcp_ml_framework.cli.main import app' succeeds."""
        from gcp_ml_framework.cli.main import app

        assert app is not None


# ---------------------------------------------------------------------------
# Compiler module import
# ---------------------------------------------------------------------------


class TestCompilerModuleImports:
    """Verify the compiler can be imported alongside the CLI."""

    def test_compiler_module_imports(self):
        """'from gcp_ml_framework.pipeline.compiler import PipelineCompiler' succeeds."""
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        assert PipelineCompiler is not None


# ---------------------------------------------------------------------------
# Build command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for the gml build CLI command."""

    def test_build_command_exists(self):
        """gml build is registered as a CLI command."""
        from gcp_ml_framework.cli.main import app

        command_names = [cmd.name for cmd in app.registered_commands]
        assert "build" in command_names

    def test_build_module_imports(self):
        """cmd_build module can be imported without error."""
        from gcp_ml_framework.cli.cmd_build import build

        assert callable(build)

    def test_build_command_constructs_gcloud_args(self, mock_context):
        """build_command() returns correct gcloud args for a pipeline."""
        from gcp_ml_framework.cli.cmd_build import build_command

        cmd = build_command(
            ctx=mock_context,
            pipeline_name="training_pipeline",
            timeout=1200,
        )
        assert cmd[0:2] == ["gcloud", "builds"]
        assert "submit" in cmd
        assert "--config" in cmd
        assert any("_PIPELINE=" in s for s in cmd)
        assert any("_TAG=" in s for s in cmd)

    def test_build_command_uses_correct_pipeline_slug(self, mock_context):
        """Pipeline name is slugified (underscores to hyphens)."""
        from gcp_ml_framework.cli.cmd_build import build_command

        cmd = build_command(ctx=mock_context, pipeline_name="training_pipeline", timeout=1200)
        joined = " ".join(cmd)
        assert "training-pipeline" in joined

    def test_build_command_timeout(self, mock_context):
        """Custom timeout is passed to gcloud."""
        from gcp_ml_framework.cli.cmd_build import build_command

        cmd = build_command(ctx=mock_context, pipeline_name="x", timeout=3600)
        assert any("3600" in s for s in cmd)


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for the gml run CLI command."""

    def test_run_command_exists(self):
        """gml run is registered as a CLI command."""
        from gcp_ml_framework.cli.main import app

        command_names = [cmd.name for cmd in app.registered_commands]
        assert "run" in command_names

    def test_run_module_imports(self):
        """cmd_run module can be imported without error."""
        from gcp_ml_framework.cli.cmd_run import run

        assert callable(run)

    def test_no_vertex_flag(self):
        """--vertex flag must NOT exist on the run command."""
        import inspect

        from gcp_ml_framework.cli.cmd_run import run

        sig = inspect.signature(run)
        assert "vertex" not in sig.parameters

    def test_no_sync_flag(self):
        """--sync flag must NOT exist on the run command."""
        import inspect

        from gcp_ml_framework.cli.cmd_run import run

        sig = inspect.signature(run)
        assert "sync" not in sig.parameters

    def test_no_no_cache_flag(self):
        """--no-cache flag must NOT exist on the run command."""
        import inspect

        from gcp_ml_framework.cli.cmd_run import run

        sig = inspect.signature(run)
        assert "no_cache" not in sig.parameters

    def test_composer_trigger_constructs_gcloud_args(self, mock_context):
        """composer_trigger_command() returns correct gcloud args."""
        from gcp_ml_framework.cli.cmd_run import composer_trigger_command

        cmd = composer_trigger_command(ctx=mock_context, pipeline_name="training_pipeline")
        assert cmd[0:2] == ["gcloud", "composer"]
        assert "environments" in cmd
        assert "run" in cmd
        assert "dags" in cmd
        assert "trigger" in cmd
        assert "--" in cmd

    def test_composer_trigger_uses_correct_dag_id(self, mock_context):
        """DAG ID follows naming convention: {namespace_bq}__{pipeline_bq_safe}."""
        from gcp_ml_framework.cli.cmd_run import composer_trigger_command

        cmd = composer_trigger_command(ctx=mock_context, pipeline_name="training_pipeline")
        expected_dag_id = mock_context.naming.dag_id("training_pipeline")
        assert expected_dag_id in cmd

    def test_composer_trigger_uses_context_env_name(self, mock_context):
        """Composer environment name comes from context."""
        from gcp_ml_framework.cli.cmd_run import composer_trigger_command

        cmd = composer_trigger_command(ctx=mock_context, pipeline_name="x")
        assert mock_context.composer_environment_name in cmd

    def test_composer_trigger_uses_region_and_project(self, mock_context):
        """Region and project are passed to gcloud."""
        from gcp_ml_framework.cli.cmd_run import composer_trigger_command

        cmd = composer_trigger_command(ctx=mock_context, pipeline_name="x")
        assert "--location" in cmd
        idx = cmd.index("--location")
        assert cmd[idx + 1] == mock_context.region
        assert "--project" in cmd
        idx = cmd.index("--project")
        assert cmd[idx + 1] == mock_context.gcp_project

    def test_local_flag_still_exists(self):
        """--local flag must exist on the run command."""
        import inspect

        from gcp_ml_framework.cli.cmd_run import run

        sig = inspect.signature(run)
        assert "local" in sig.parameters


# ---------------------------------------------------------------------------
# Init templates
# ---------------------------------------------------------------------------


class TestInitTemplates:
    """Verify init templates use correct env var names and current API."""

    def test_dot_env_template_uses_correct_var_names(self):
        """_DOT_ENV must use TEAM/PROJECT/ENVIRONMENT, not GML_* prefix."""
        from gcp_ml_framework.cli.cmd_init import _DOT_ENV

        assert "GML_TEAM" not in _DOT_ENV
        assert "GML_PROJECT" not in _DOT_ENV
        assert "GML_ENVIRONMENT" not in _DOT_ENV
        assert "GML_GCP__" not in _DOT_ENV
        assert "TEAM=" in _DOT_ENV
        assert "PROJECT=" in _DOT_ENV
        assert "ENVIRONMENT=" in _DOT_ENV
        assert "GCP_PROJECT_ID=" in _DOT_ENV

    def test_pipeline_template_uses_model_name(self):
        """_PIPELINE_PY must use model_name, not endpoint_name."""
        from gcp_ml_framework.cli.cmd_init import _PIPELINE_PY

        assert "endpoint_name=" not in _PIPELINE_PY
        assert "model_name=" in _PIPELINE_PY

    def test_ci_templates_use_correct_var_names(self):
        """CI workflow templates must use TEAM/PROJECT, not GML_TEAM/GML_PROJECT."""
        from gcp_ml_framework.cli.cmd_init import (
            _CI_DEV_YAML,
            _CI_STAGE_YAML,
            _PROMOTE_YAML,
            _TEARDOWN_YAML,
        )

        for name, template in [
            ("ci-dev", _CI_DEV_YAML),
            ("ci-stage", _CI_STAGE_YAML),
            ("promote", _PROMOTE_YAML),
            ("teardown", _TEARDOWN_YAML),
        ]:
            assert "GML_TEAM" not in template, f"{name} uses GML_TEAM"
            assert "GML_PROJECT" not in template, f"{name} uses GML_PROJECT"
            assert "GML_GCP__" not in template, f"{name} uses GML_GCP__"
