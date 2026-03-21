"""Unit tests for RegisterModel (gcp_ml_framework.components.ml.register)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.register import RegisterModel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_aiplatform():
    """Inject a MagicMock for google.cloud.aiplatform into sys.modules.

    register.py does ``from google.cloud import aiplatform`` inside execute(),
    so we need the module present in sys.modules before the import runs.
    We also set the attribute on google.cloud to ensure ``from google.cloud
    import aiplatform`` resolves to the mock even if the real SDK was
    imported earlier in the test process.
    """
    import google.cloud

    mock_aip = MagicMock()
    token = "google.cloud.aiplatform"
    original_module = sys.modules.get(token)
    original_attr = getattr(google.cloud, "aiplatform", None)
    sys.modules[token] = mock_aip
    google.cloud.aiplatform = mock_aip
    yield mock_aip
    # Restore
    if original_module is None:
        sys.modules.pop(token, None)
    else:
        sys.modules[token] = original_module
    if original_attr is not None:
        google.cloud.aiplatform = original_attr
    elif hasattr(google.cloud, "aiplatform"):
        delattr(google.cloud, "aiplatform")


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestRegisterModelInstantiation:
    """Verify RegisterModel fields and defaults."""

    def test_register_model_instantiation(self):
        """RegisterModel creates with default fields."""
        rm = RegisterModel()
        assert rm.model_uri == ""
        assert rm.model_display_name == ""
        assert rm.serving_container_image == ""
        assert rm.labels == {}
        assert rm.description == ""
        assert rm.component_name == "register_model"

    def test_register_model_is_base_component(self):
        """RegisterModel is an instance of BaseComponent."""
        rm = RegisterModel()
        assert isinstance(rm, BaseComponent)


# ---------------------------------------------------------------------------
# execute() — Model.upload()
# ---------------------------------------------------------------------------


class TestRegisterModelExecute:
    """Verify execute() calls aiplatform.Model.upload() correctly."""

    def test_register_model_execute_calls_upload(self, mock_aiplatform: MagicMock):
        """execute() initialises aiplatform and calls Model.upload()."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us-central1/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            serving_container_image="gcr.io/proj/serving:v1",
            labels={"team": "ml"},
            description="Churn prediction model",
        )
        rm.execute()

        mock_aiplatform.init.assert_called_once_with(project="test-project", location="us-central1")
        call_kwargs = mock_aiplatform.Model.upload.call_args.kwargs
        assert call_kwargs["display_name"] == "churn-model"
        assert call_kwargs["artifact_uri"] == "gs://bucket/model"
        assert call_kwargs["serving_container_image_uri"] == "gcr.io/proj/serving:v1"
        assert call_kwargs["labels"] == {"team": "ml"}
        assert call_kwargs["description"] == "Churn prediction model"
        # Custom image → CPR routes are included
        assert call_kwargs["serving_container_predict_route"] == "/predict"
        assert call_kwargs["serving_container_health_route"] == "/health"

    def test_register_model_writes_output_uri(self, mock_aiplatform: MagicMock, tmp_path: Path):
        """execute() writes model resource_name to output_uri_path."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us-central1/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        output_file = tmp_path / "output" / "uri"

        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            output_uri_path=str(output_file),
        )
        rm.execute()

        assert output_file.exists()
        assert output_file.read_text() == "projects/123/locations/us-central1/models/456"


# ---------------------------------------------------------------------------
# execute()→run() lifecycle
# ---------------------------------------------------------------------------


class TestRegisterModelLifecycle:
    """Verify execute()→run() lifecycle."""

    def test_execute_calls_run(self, mock_aiplatform: MagicMock):
        """execute() should delegate to run()."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        rm = RegisterModel(project="test-project", region="us-central1")
        return_val = "projects/123/locations/us/models/456"
        with patch.object(RegisterModel, "run", return_value=return_val) as mock_run:
            rm.execute()
            mock_run.assert_called_once()

    def test_execute_writes_run_return_value(self, mock_aiplatform: MagicMock, tmp_path: Path):
        """execute() writes the return value of run() to output_uri_path."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        output_file = tmp_path / "output" / "uri"
        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="test-model",
            output_uri_path=str(output_file),
        )
        rm.execute()
        assert output_file.exists()
        assert output_file.read_text() == "projects/123/locations/us/models/456"


# ---------------------------------------------------------------------------
# CPR routes for custom serving containers
# ---------------------------------------------------------------------------


class TestRegisterModelCPR:
    """Verify CPR kwargs are passed for custom containers, not pre-built."""

    def test_cpr_kwargs_for_custom_image(self, mock_aiplatform: MagicMock):
        """Custom serving image → upload includes CPR routes."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="cpr-model",
            serving_container_image="us-central1-docker.pkg.dev/proj/repo/pipe-serving:tag",
        )
        rm.execute()

        call_kwargs = mock_aiplatform.Model.upload.call_args
        assert call_kwargs.kwargs.get("serving_container_predict_route") == "/predict"
        assert call_kwargs.kwargs.get("serving_container_health_route") == "/health"
        assert call_kwargs.kwargs.get("serving_container_ports") == [8080]
        assert call_kwargs.kwargs.get("serving_container_command") == [
            "python", "-m", "gcp_ml_framework.serving.handler",
        ]

    def test_no_cpr_kwargs_for_prebuilt_image(self, mock_aiplatform: MagicMock):
        """Pre-built Vertex AI image → no CPR kwargs."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="sklearn-model",
            serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest",
        )
        rm.execute()

        call_kwargs = mock_aiplatform.Model.upload.call_args
        assert "serving_container_predict_route" not in (call_kwargs.kwargs or {})
        assert "serving_container_health_route" not in (call_kwargs.kwargs or {})
