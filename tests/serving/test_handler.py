"""Unit tests for the serving handler (gcp_ml_framework.serving.handler)."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeWFile(io.BytesIO):
    """Writable bytes buffer for HTTPServer response body."""


def _make_handler(method: str, path: str, body: dict | None = None):
    """Build a PredictionHandler wired to a fake request/response."""
    from gcp_ml_framework.serving.handler import PredictionHandler

    body_bytes = json.dumps(body).encode() if body else b""

    handler = PredictionHandler.__new__(PredictionHandler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body_bytes))}
    handler.rfile = io.BytesIO(body_bytes)
    handler.wfile = _FakeWFile()
    handler._sent_status = None
    handler._sent_headers = {}

    # Capture send_response / send_header / end_headers
    def _send_response(code, message=None):
        handler._sent_status = code

    def _send_header(key, value):
        handler._sent_headers[key] = value

    handler.send_response = _send_response
    handler.send_header = _send_header
    handler.end_headers = lambda: None

    return handler


def _response_body(handler) -> dict:
    return json.loads(handler.wfile.getvalue().decode())


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health returns 200 with healthy status."""

    def test_health_returns_200(self):
        handler = _make_handler("GET", "/health")
        handler.do_GET()

        assert handler._sent_status == 200
        assert _response_body(handler) == {"status": "healthy"}

    def test_unknown_get_returns_404(self):
        handler = _make_handler("GET", "/unknown")
        handler.do_GET()

        assert handler._sent_status == 404


# ---------------------------------------------------------------------------
# /predict endpoint
# ---------------------------------------------------------------------------


class TestPredictEndpoint:
    """POST /predict returns predictions from the model."""

    def test_predict_returns_predictions(self):
        import gcp_ml_framework.serving.handler as handler_mod

        mock_model = MagicMock()
        mock_model.predict.return_value = pd.DataFrame({"price": [100.0, 200.0]})
        original = handler_mod._model
        handler_mod._model = mock_model

        try:
            handler = _make_handler(
                "POST", "/predict",
                body={"instances": [{"area": 1000}, {"area": 2000}]},
            )
            handler.do_POST()

            assert handler._sent_status == 200
            body = _response_body(handler)
            assert "predictions" in body
            assert len(body["predictions"]) == 2
            mock_model.predict.assert_called_once()
        finally:
            handler_mod._model = original

    def test_predict_unknown_route_returns_404(self):
        handler = _make_handler("POST", "/unknown", body={})
        handler.do_POST()

        assert handler._sent_status == 404


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestPredictErrorHandling:
    """POST /predict with malformed input returns 400."""

    def test_missing_instances_key(self):
        import gcp_ml_framework.serving.handler as handler_mod

        mock_model = MagicMock()
        original = handler_mod._model
        handler_mod._model = mock_model

        try:
            handler = _make_handler(
                "POST", "/predict",
                body={"data": [1, 2, 3]},
            )
            handler.do_POST()

            assert handler._sent_status == 400
            body = _response_body(handler)
            assert "error" in body
        finally:
            handler_mod._model = original

    def test_invalid_json(self):
        from gcp_ml_framework.serving.handler import PredictionHandler

        handler = PredictionHandler.__new__(PredictionHandler)
        handler.path = "/predict"
        handler.headers = {"Content-Length": "11"}
        handler.rfile = io.BytesIO(b"not-json!!!")
        handler.wfile = _FakeWFile()
        handler._sent_status = None
        handler._sent_headers = {}
        handler.send_response = lambda code, msg=None: setattr(handler, "_sent_status", code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        handler.do_POST()

        assert handler._sent_status == 400


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


class TestModelLoading:
    """_load_model downloads from GCS and unpickles."""

    def test_load_model_from_gcs(self, tmp_path):
        import pickle

        # Use a simple dict as a picklable stand-in for a model
        fake_model = {"type": "fake_model", "version": 1}
        pkl_path = tmp_path / "model.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump(fake_model, f)

        import shutil

        mock_blob = MagicMock()
        mock_blob.download_to_filename.side_effect = (
            lambda dest: shutil.copy(str(pkl_path), dest)
        )

        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        with (
            patch.dict("os.environ", {"AIP_STORAGE_URI": "gs://my-bucket/models/v1"}),
            patch("google.cloud.storage.Client", return_value=mock_client),
        ):
            from gcp_ml_framework.serving.handler import _load_model

            model = _load_model()

        mock_client.bucket.assert_called_with("my-bucket")
        mock_bucket.blob.assert_called_with("models/v1/model.pkl")
        assert model == {"type": "fake_model", "version": 1}

    def test_load_model_missing_env_var(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(RuntimeError, match="AIP_STORAGE_URI"),
        ):
            from gcp_ml_framework.serving.handler import _load_model

            _load_model()
