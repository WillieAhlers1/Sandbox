"""Unit tests for run_deploy() model lookup, endpoint management, and monitoring."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_aiplatform():
    """Inject a MagicMock for google.cloud.aiplatform into sys.modules."""
    import google.cloud

    mock_aip = MagicMock()
    token = "google.cloud.aiplatform"
    original_module = sys.modules.get(token)
    original_attr = getattr(google.cloud, "aiplatform", None)
    sys.modules[token] = mock_aip
    google.cloud.aiplatform = mock_aip

    # Setup default mocks — Model.list returns a registered model
    mock_model = MagicMock()
    mock_model.resource_name = "projects/test/locations/us/models/123"
    mock_aip.Model.list.return_value = [mock_model]

    mock_endpoint = MagicMock()
    mock_endpoint.resource_name = "projects/test/locations/us/endpoints/456"
    mock_aip.Endpoint.list.return_value = [mock_endpoint]

    yield mock_aip

    if original_module is None:
        sys.modules.pop(token, None)
    else:
        sys.modules[token] = original_module
    if original_attr is not None:
        google.cloud.aiplatform = original_attr
    elif hasattr(google.cloud, "aiplatform"):
        delattr(google.cloud, "aiplatform")


_COMMON_KWARGS = {
    "project": "test-project",
    "region": "us-east4",
    "model_display_name": "test-model",
    "endpoint_display_name": "test-endpoint",
    "machine_type": "n2-standard-2",
    "min_replica_count": 1,
    "max_replica_count": 1,
    "traffic_split": {"new": 100},
    "output_uri_path": "",
}


class TestRunDeployModelLookup:
    """run_deploy() looks up a registered model by display_name."""

    def test_model_looked_up_by_display_name(self, mock_aiplatform):
        """run_deploy calls Model.list with a display_name filter."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(**_COMMON_KWARGS)

        mock_aiplatform.Model.list.assert_called_once_with(
            filter='display_name="test-model"',
            project="test-project",
            location="us-east4",
        )

    def test_raises_when_no_model_found(self, mock_aiplatform):
        """run_deploy raises ValueError when no registered model matches."""
        from gcp_ml_framework.utils.vertex import run_deploy

        mock_aiplatform.Model.list.return_value = []

        with pytest.raises(ValueError, match="No registered model found"):
            run_deploy(**_COMMON_KWARGS)

    def test_endpoint_reused_when_exists(self, mock_aiplatform):
        """When endpoint exists, reuse it instead of creating new."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(**_COMMON_KWARGS)

        mock_aiplatform.Endpoint.list.assert_called_once()
        mock_aiplatform.Endpoint.create.assert_not_called()

    def test_endpoint_created_when_not_exists(self, mock_aiplatform):
        """When no endpoint exists, create new."""
        from gcp_ml_framework.utils.vertex import run_deploy

        mock_aiplatform.Endpoint.list.return_value = []
        mock_new_endpoint = MagicMock()
        mock_new_endpoint.resource_name = "projects/test/endpoints/789"
        mock_aiplatform.Endpoint.create.return_value = mock_new_endpoint

        run_deploy(**_COMMON_KWARGS)

        mock_aiplatform.Endpoint.create.assert_called_once()


class TestRunDeployMonitoring:
    """run_deploy() monitoring job creation."""

    def test_monitoring_disabled_by_default(self, mock_aiplatform):
        """No monitoring job created when enable_monitoring not set."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(**_COMMON_KWARGS)

        mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_not_called()

    def test_monitoring_enabled_creates_job(self, mock_aiplatform):
        """When enable_monitoring=True, creates monitoring job."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            enable_monitoring=True,
            monitoring_alert_email="team@example.com",
            **_COMMON_KWARGS,
        )

        mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_called_once()
