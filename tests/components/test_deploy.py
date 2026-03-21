"""Unit tests for DeployModel (gcp_ml_framework.components.ml.deploy)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.deploy import DeployModel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestDeployModelInstantiation:
    """Verify DeployModel fields, defaults, and overrides."""

    def test_deploy_model_instantiation(self):
        """DeployModel creates with endpoint_name (required) and sensible defaults."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert isinstance(dm, BaseComponent)
        assert dm.endpoint_name == "churn-v1"
        assert dm.model_uri == ""
        assert dm.model_display_name == ""
        assert dm.endpoint_display_name == ""
        assert dm.serving_container_image == ""
        assert dm.component_name == "deploy_model"

    def test_deploy_model_machine_type_override(self):
        """DeployModel defaults machine_type to n2-standard-2, overriding BaseComponent."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert dm.machine_type == "n2-standard-2"
        # Confirm base default is different
        base = BaseComponent()
        assert base.machine_type == "n2-standard-4"

    def test_deploy_model_traffic_split_default(self):
        """traffic_split defaults to {"new": 100}."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert dm.traffic_split == {"new": 100}


# ---------------------------------------------------------------------------
# execute() delegation
# ---------------------------------------------------------------------------


class TestDeployModelExecute:
    """Verify execute() delegates to utils.vertex.run_deploy with correct args."""

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_deploy_model_execute_delegates(self, mock_run_deploy: MagicMock):
        """execute() calls run_deploy() with all the component's field values."""
        dm = DeployModel(
            endpoint_name="churn-v1",
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            endpoint_display_name="churn-endpoint",
            serving_container_image="gcr.io/proj/serving:v1",
            machine_type="n2-standard-4",
            min_replica_count=2,
            max_replica_count=5,
            traffic_split={"new": 50, "current": 50},
            output_uri_path="/tmp/output_uri",
        )
        dm.execute()

        mock_run_deploy.assert_called_once_with(
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            endpoint_display_name="churn-endpoint",
            serving_container_image="gcr.io/proj/serving:v1",
            machine_type="n2-standard-4",
            min_replica_count=2,
            max_replica_count=5,
            traffic_split={"new": 50, "current": 50},
            output_uri_path="/tmp/output_uri",
            enable_monitoring=False,
            monitoring_alert_email="",
            monitoring_log_sample_rate=0.8,
            monitoring_monitor_interval=3600,
            monitoring_skew_thresholds={},
            monitoring_drift_thresholds={},
        )


# ---------------------------------------------------------------------------
# execute()→run() lifecycle
# ---------------------------------------------------------------------------


class TestDeployModelLifecycle:
    """Verify execute()→run() lifecycle."""

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_execute_calls_run(self, mock_run_deploy: MagicMock):
        """execute() should delegate to run()."""
        dm = DeployModel(endpoint_name="test-ep", project="test-project", region="us-central1")
        with patch.object(DeployModel, "run") as mock_run:
            dm.execute()
            mock_run.assert_called_once()

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_subclass_run_override(self, mock_run_deploy: MagicMock):
        """Data scientist subclass overriding run() should have custom code execute."""
        class CustomDeploy(DeployModel):
            def run(self) -> None:
                self._custom_called = True

        cd = CustomDeploy(endpoint_name="test-ep", project="test-project", region="us-central1")
        cd.execute()
        assert cd._custom_called is True
        mock_run_deploy.assert_not_called()


# ---------------------------------------------------------------------------
# Monitoring fields (5.5)
# ---------------------------------------------------------------------------


class TestDeployModelMonitoring:
    """Verify monitoring fields and passthrough to run_deploy()."""

    def test_monitoring_defaults(self):
        """Monitoring is disabled by default."""
        dm = DeployModel(endpoint_name="test")
        assert dm.enable_monitoring is False
        assert dm.monitoring_alert_email == ""
        assert dm.monitoring_log_sample_rate == 0.8
        assert dm.monitoring_monitor_interval == 3600
        assert dm.monitoring_skew_thresholds == {}
        assert dm.monitoring_drift_thresholds == {}

    def test_monitoring_enabled(self):
        """Monitoring fields accepted when enabled."""
        dm = DeployModel(
            endpoint_name="test",
            enable_monitoring=True,
            monitoring_alert_email="a@b.com",
            monitoring_skew_thresholds={"area": 0.3},
        )
        assert dm.enable_monitoring is True
        assert dm.monitoring_alert_email == "a@b.com"
        assert dm.monitoring_skew_thresholds == {"area": 0.3}

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_monitoring_fields_passed_to_run_deploy(self, mock_run_deploy: MagicMock):
        """run() passes all monitoring fields to run_deploy()."""
        dm = DeployModel(
            endpoint_name="test-ep",
            project="test-project",
            region="us-east4",
            enable_monitoring=True,
            monitoring_alert_email="team@co.com",
            monitoring_skew_thresholds={"area": 0.3},
        )
        dm.execute()

        call_kwargs = mock_run_deploy.call_args[1]
        assert call_kwargs["enable_monitoring"] is True
        assert call_kwargs["monitoring_alert_email"] == "team@co.com"
        assert call_kwargs["monitoring_skew_thresholds"] == {"area": 0.3}
