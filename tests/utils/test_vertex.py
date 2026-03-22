"""Unit tests for run_deploy() smart model resolution and monitoring."""

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

    # Setup default mocks
    mock_model = MagicMock()
    mock_model.resource_name = "projects/test/locations/us/models/123"
    mock_aip.Model.upload.return_value = mock_model
    mock_aip.Model.return_value = mock_model

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
    "serving_container_image": "gcr.io/proj/serving:v1",
    "machine_type": "n2-standard-2",
    "min_replica_count": 1,
    "max_replica_count": 1,
    "traffic_split": {"new": 100},
    "output_uri_path": "",
}


class TestSmartModelResolution:
    """run_deploy() detects model_uri format and acts accordingly."""

    def test_registered_model_skips_upload(self, mock_aiplatform):
        """When model_uri starts with 'projects/', use Model() directly — no upload."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="projects/my-proj/locations/us-east4/models/123",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.Model.assert_called_with(
            "projects/my-proj/locations/us-east4/models/123"
        )
        mock_aiplatform.Model.upload.assert_not_called()

    def test_gcs_path_uploads_model(self, mock_aiplatform):
        """When model_uri starts with 'gs://', upload via Model.upload()."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="gs://bucket/models/v1",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.Model.upload.assert_called_once()

    def test_endpoint_reused_when_exists(self, mock_aiplatform):
        """When endpoint exists, reuse it instead of creating new."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="gs://bucket/models/v1",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.Endpoint.list.assert_called_once()
        mock_aiplatform.Endpoint.create.assert_not_called()

    def test_endpoint_created_when_not_exists(self, mock_aiplatform):
        """When no endpoint exists, create new."""
        from gcp_ml_framework.utils.vertex import run_deploy

        mock_aiplatform.Endpoint.list.return_value = []
        mock_new_endpoint = MagicMock()
        mock_new_endpoint.resource_name = "projects/test/endpoints/789"
        mock_aiplatform.Endpoint.create.return_value = mock_new_endpoint

        run_deploy(
            model_uri="gs://bucket/models/v1",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.Endpoint.create.assert_called_once()


class TestRunDeployCPR:
    """run_deploy() adds CPR kwargs for custom serving containers."""

    def test_cpr_kwargs_for_custom_image(self, mock_aiplatform):
        """Custom serving image → upload includes CPR routes."""
        from gcp_ml_framework.utils.vertex import run_deploy

        custom_kwargs = {
            **_COMMON_KWARGS,
            "serving_container_image": (
                "us-central1-docker.pkg.dev/proj/repo/pipe-serving:tag"
            ),
        }
        run_deploy(model_uri="gs://bucket/models/v1", **custom_kwargs)
        call_kwargs = mock_aiplatform.Model.upload.call_args
        assert call_kwargs.kwargs.get("serving_container_predict_route") == "/predict"
        assert call_kwargs.kwargs.get("serving_container_health_route") == "/health"
        assert call_kwargs.kwargs.get("serving_container_ports") == [8080]

    def test_no_cpr_kwargs_for_prebuilt_image(self, mock_aiplatform):
        """Pre-built Vertex AI image → no CPR kwargs."""
        from gcp_ml_framework.utils.vertex import run_deploy

        prebuilt_kwargs = {
            **_COMMON_KWARGS,
            "serving_container_image": (
                "us-docker.pkg.dev/vertex-ai/prediction/"
                "sklearn-cpu.1-3:latest"
            ),
        }
        run_deploy(model_uri="gs://bucket/models/v1", **prebuilt_kwargs)
        call_kwargs = mock_aiplatform.Model.upload.call_args
        assert "serving_container_predict_route" not in (call_kwargs.kwargs or {})

    def test_registered_model_skips_cpr(self, mock_aiplatform):
        """When model_uri is projects/ resource name, no upload happens — no CPR needed."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="projects/my-proj/locations/us-east4/models/123",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.Model.upload.assert_not_called()


class TestRunDeployMonitoring:
    """run_deploy() monitoring job creation."""

    def test_monitoring_disabled_by_default(self, mock_aiplatform):
        """No monitoring job created when enable_monitoring not set."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="gs://bucket/models/v1",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_not_called()

    def test_monitoring_enabled_creates_job(self, mock_aiplatform):
        """When enable_monitoring=True, creates monitoring job."""
        from gcp_ml_framework.utils.vertex import run_deploy

        run_deploy(
            model_uri="gs://bucket/models/v1",
            enable_monitoring=True,
            monitoring_alert_email="team@example.com",
            **_COMMON_KWARGS,
        )
        mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_called_once()
