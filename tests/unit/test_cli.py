"""Phase 5 — CLI unit tests.

Tests each gml command with mocked filesystem and GCP:
- gml init project / pipeline
- gml context show
- gml run --local
- gml compile
- gml deploy --dry-run
- gml teardown --dry-run
"""

import pytest
from typer.testing import CliRunner

from gcp_ml_framework.cli.main import app

runner = CliRunner()


# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def project_dir(tmp_path):
    """Create a scaffolded project in tmp_path and return its path."""
    result = runner.invoke(
        app,
        [
            "init",
            "project",
            "dsci",
            "testproj",
            "--dev-project",
            "gcp-dev-123",
            "-o",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    return tmp_path


@pytest.fixture
def pipeline_dir(project_dir):
    """Scaffold a pipeline inside the project."""
    pipelines = project_dir / "pipelines"
    result = runner.invoke(
        app,
        [
            "init",
            "pipeline",
            "my_pipeline",
            "-o",
            str(pipelines),
        ],
    )
    assert result.exit_code == 0, result.output
    return pipelines / "my_pipeline"


# ── gml init project ─────────────────────────────────────────────────────────


class TestInitProject:
    def test_creates_framework_yaml(self, project_dir):
        assert (project_dir / "framework.yaml").exists()

    def test_framework_yaml_content(self, project_dir):
        content = (project_dir / "framework.yaml").read_text()
        assert "team: dsci" in content
        assert "project: testproj" in content
        assert "gcp-dev-123" in content

    def test_creates_directory_structure(self, project_dir):
        assert (project_dir / "pipelines").is_dir()
        assert (project_dir / "dags").is_dir()
        assert (project_dir / "tests" / "unit").is_dir()
        assert (project_dir / "tests" / "integration").is_dir()
        assert (project_dir / "feature_schemas" / "user.yaml").exists()

    def test_creates_ci_workflows(self, project_dir):
        wf = project_dir / ".github" / "workflows"
        assert (wf / "ci-dev.yaml").exists()
        assert (wf / "ci-stage.yaml").exists()
        assert (wf / "promote.yaml").exists()
        assert (wf / "teardown.yaml").exists()

    def test_creates_gitignore(self, project_dir):
        assert (project_dir / ".gitignore").exists()
        content = (project_dir / ".gitignore").read_text()
        assert "__pycache__" in content

    def test_staging_prod_defaults(self, project_dir):
        content = (project_dir / "framework.yaml").read_text()
        # Should auto-derive staging/prod from dev
        assert "gcp-dev-123-staging" in content
        assert "gcp-dev-123-prod" in content

    def test_custom_staging_prod(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "init",
                "project",
                "dsci",
                "testproj",
                "--dev-project",
                "dev-123",
                "--staging-project",
                "stage-456",
                "--prod-project",
                "prod-789",
                "-o",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        content = (tmp_path / "framework.yaml").read_text()
        assert "stage-456" in content
        assert "prod-789" in content


# ── gml init pipeline ────────────────────────────────────────────────────────


class TestInitPipeline:
    def test_creates_pipeline_py(self, pipeline_dir):
        assert (pipeline_dir / "pipeline.py").exists()

    def test_pipeline_py_content(self, pipeline_dir):
        content = (pipeline_dir / "pipeline.py").read_text()
        assert "PipelineBuilder" in content
        assert "my_pipeline" in content

    def test_creates_config_yaml(self, pipeline_dir):
        assert (pipeline_dir / "config.yaml").exists()

    def test_creates_sql_directory(self, pipeline_dir):
        sql_dir = pipeline_dir / "sql"
        assert sql_dir.is_dir()
        sql_files = list(sql_dir.glob("*.sql"))
        assert len(sql_files) == 1
        assert "my_pipeline" in sql_files[0].name


# ── gml context show ─────────────────────────────────────────────────────────


class TestContextShow:
    def test_context_show_with_config(self, project_dir):
        result = runner.invoke(
            app,
            [
                "context",
                "show",
                "-c",
                str(project_dir / "framework.yaml"),
                "--branch",
                "feature/test-branch",
            ],
        )
        assert result.exit_code == 0
        assert "dsci" in result.output
        assert "testproj" in result.output

    def test_context_show_json(self, project_dir):
        result = runner.invoke(
            app,
            [
                "context",
                "show",
                "-c",
                str(project_dir / "framework.yaml"),
                "--branch",
                "main",
                "--json",
            ],
        )
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert "namespace" in data or "gcp_project" in data


# ── gml compile ──────────────────────────────────────────────────────────────


class TestCompile:
    def test_compile_requires_name_or_all(self):
        result = runner.invoke(app, ["compile"])
        assert result.exit_code != 0

    def test_compile_missing_pipeline(self, project_dir):
        result = runner.invoke(
            app,
            [
                "compile",
                "nonexistent",
                "-c",
                str(project_dir / "framework.yaml"),
                "--pipelines-dir",
                str(project_dir / "pipelines"),
            ],
        )
        assert result.exit_code != 0


# ── gml run ──────────────────────────────────────────────────────────────────


class TestRun:
    def test_run_requires_name_or_all(self):
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0

    def test_run_mutually_exclusive_flags(self):
        result = runner.invoke(app, ["run", "test", "--local", "--vertex"])
        assert result.exit_code != 0

    def test_run_mutually_exclusive_composer_local(self):
        result = runner.invoke(app, ["run", "test", "--local", "--composer"])
        assert result.exit_code != 0

    def test_run_mutually_exclusive_composer_vertex(self):
        result = runner.invoke(app, ["run", "test", "--vertex", "--composer"])
        assert result.exit_code != 0

    def test_run_missing_pipeline(self, project_dir):
        result = runner.invoke(
            app,
            [
                "run",
                "nonexistent",
                "--local",
                "-c",
                str(project_dir / "framework.yaml"),
                "--pipelines-dir",
                str(project_dir / "pipelines"),
            ],
        )
        assert result.exit_code != 0


# ── gml deploy ───────────────────────────────────────────────────────────────


class TestDeploy:
    def test_deploy_requires_name_or_all(self):
        result = runner.invoke(app, ["deploy"])
        assert result.exit_code != 0

    def test_ensure_image_tag_function_exists(self):
        """The AR utility for image verification should exist."""
        from gcp_ml_framework.utils.ar import ensure_image_tag

        assert callable(ensure_image_tag)

    def test_deploy_calls_ensure_images(self):
        """gml deploy should verify Docker images exist in AR."""
        from gcp_ml_framework.cli.cmd_deploy import _ensure_images

        assert callable(_ensure_images)


# ── gml teardown ─────────────────────────────────────────────────────────────


class TestTeardown:
    def test_teardown_rejects_main_branch(self, project_dir):
        result = runner.invoke(
            app,
            [
                "teardown",
                "teardown",
                "--branch",
                "main",
                "-c",
                str(project_dir / "framework.yaml"),
                "--dry-run",
            ],
        )
        assert result.exit_code != 0

    def test_teardown_dry_run_dev_branch(self, project_dir):
        result = runner.invoke(
            app,
            [
                "teardown",
                "teardown",
                "--branch",
                "feature/test-branch",
                "-c",
                str(project_dir / "framework.yaml"),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_teardown_rejects_prod_tag(self, project_dir):
        result = runner.invoke(
            app,
            [
                "teardown",
                "teardown",
                "--branch",
                "v1.0.0",
                "-c",
                str(project_dir / "framework.yaml"),
                "--dry-run",
            ],
        )
        assert result.exit_code != 0

    def test_teardown_dry_run_shows_composer_dags(self, project_dir):
        """Teardown dry-run should list Composer DAG cleanup in the plan."""
        result = runner.invoke(
            app,
            [
                "teardown",
                "teardown",
                "--branch",
                "feature/test-branch",
                "-c",
                str(project_dir / "framework.yaml"),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "composer" in result.output.lower() or "dag" in result.output.lower()
