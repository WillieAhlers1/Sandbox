"""Unit tests for ComposerRunner — Airflow REST API trigger and unpause."""

from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.config import FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.dag.runner import ComposerRunner


@pytest.fixture
def composer_ctx():
    cfg = FrameworkConfig(
        team="test",
        project="myproj",
        branch="feature/test",
        gcp=GCPConfig(
            dev_project_id="test-project",
            staging_project_id="test-staging",
            prod_project_id="test-prod",
            region="us-east4",
            composer_environment_name="test-composer",
        ),
    )
    return MLContext.from_config(cfg)


@pytest.fixture
def runner(composer_ctx):
    r = ComposerRunner(composer_ctx)
    # Pre-set the Airflow URI to avoid gcloud subprocess calls
    r._airflow_uri = "https://airflow.example.com"
    return r


class TestComposerRunner:
    def test_resolve_dag_id(self, runner, composer_ctx):
        dag_id = runner.resolve_dag_id("sales_analytics")
        expected = composer_ctx.naming.dag_id("sales_analytics")
        assert dag_id == expected

    def test_build_trigger_url(self, runner):
        url = runner._build_trigger_url("my_dag")
        assert url == "https://airflow.example.com/api/v1/dags/my_dag/dagRuns"

    @patch("gcp_ml_framework.dag.runner.ComposerRunner._get_auth_headers")
    def test_trigger_success(self, mock_auth, runner):
        mock_auth.return_value = {"Authorization": "Bearer fake"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "dag_run_id": "manual__2026-03-01",
            "state": "queued",
        }

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = runner._trigger_dag_run("my_dag", "2026-03-01")

        mock_post.assert_called_once()
        assert result["state"] == "queued"

    @patch("gcp_ml_framework.dag.runner.ComposerRunner._get_auth_headers")
    def test_trigger_conflict_409(self, mock_auth, runner):
        mock_auth.return_value = {"Authorization": "Bearer fake"}
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        mock_resp.ok = False

        with patch("requests.post", return_value=mock_resp):
            result = runner._trigger_dag_run("my_dag", "2026-03-01")

        assert result["conflict"] is True
        assert result["state"] == "queued"

    @patch("gcp_ml_framework.dag.runner.ComposerRunner._get_auth_headers")
    def test_trigger_error_raises(self, mock_auth, runner):
        mock_auth.return_value = {"Authorization": "Bearer fake"}
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.ok = False
        mock_resp.text = "Internal Server Error"

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="Failed to trigger DAG"):
                runner._trigger_dag_run("my_dag", "2026-03-01")

    @patch("gcp_ml_framework.dag.runner.ComposerRunner._get_auth_headers")
    def test_unpause_success(self, mock_auth, runner):
        mock_auth.return_value = {"Authorization": "Bearer fake"}
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch("requests.patch", return_value=mock_resp):
            runner.unpause_dag("my_dag")  # should not raise

    @patch("gcp_ml_framework.dag.runner.ComposerRunner._get_auth_headers")
    def test_unpause_failure_best_effort(self, mock_auth, runner):
        """unpause failure should not raise — it's best-effort."""
        mock_auth.return_value = {"Authorization": "Bearer fake"}
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "error"

        with patch("requests.patch", return_value=mock_resp):
            runner.unpause_dag("my_dag")  # should not raise

    def test_get_auth_headers(self):
        """_get_auth_headers uses google.auth.default for ADC."""
        mock_creds = MagicMock()
        mock_creds.token = "test-token"

        with patch("google.auth.default", return_value=(mock_creds, "project")):
            with patch("google.auth.transport.requests.Request"):
                ctx = MagicMock()
                runner = ComposerRunner(ctx)
                headers = runner._get_auth_headers()

        assert headers["Authorization"] == "Bearer test-token"
        mock_creds.refresh.assert_called_once()
