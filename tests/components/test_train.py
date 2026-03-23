"""Unit tests for TrainModel (gcp_ml_framework.components.ml.train)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.train import TrainModel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestTrainModelInstantiation:
    """Verify TrainModel creates correctly and exposes the expected fields."""

    def test_train_model_instantiation(self):
        """TrainModel creates with default fields; has model_output_uri, job_name, etc."""
        tm = TrainModel()
        assert isinstance(tm, BaseComponent)
        assert tm.model_output_uri == ""
        assert tm.job_name == ""
        assert tm.run_id == ""
        assert tm.component_name == ""

    def test_train_model_inherits_machine_type(self):
        """TrainModel inherits machine_type default from BaseComponent (n2-standard-4)."""
        tm = TrainModel()
        assert tm.machine_type == "n2-standard-4"


# ---------------------------------------------------------------------------
# execute() lifecycle
# ---------------------------------------------------------------------------


class TestTrainModelExecute:
    """Verify execute() creates a temp dir, calls run(), uploads, and writes output."""

    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_train_model_execute_uploads(self, mock_upload: MagicMock, tmp_path: Path):
        """execute() calls run(), uses returned path for GCS upload."""
        model_dir = tmp_path / "artifacts"
        model_dir.mkdir()
        (model_dir / "model.pkl").write_text("fake-model")

        class _TestTrainer(TrainModel):
            def run(self) -> Path:
                return model_dir

        trainer = _TestTrainer(
            model_output_uri="gs://bucket/models/test",
            project="test-project",
        )
        trainer.execute()

        # upload_file was called for our model file
        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        assert str(call_args[0][0]).endswith("model.pkl")
        assert "gs://bucket/models/test" in call_args[0][1]

    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_train_model_writes_output_uri(self, mock_upload: MagicMock, tmp_path: Path):
        """execute() writes model_output_uri to the output_uri_path file."""
        output_file = tmp_path / "output" / "uri"
        model_dir = tmp_path / "artifacts"
        model_dir.mkdir()

        class _TestTrainer(TrainModel):
            def run(self) -> Path:
                return model_dir

        trainer = _TestTrainer(
            model_output_uri="gs://bucket/models/churn/latest",
            output_uri_path=str(output_file),
        )
        trainer.execute()

        assert output_file.exists()
        assert output_file.read_text() == "gs://bucket/models/churn/latest"


# ---------------------------------------------------------------------------
# Experiment tracking (5.3)
# ---------------------------------------------------------------------------


class TestTrainModelExperiments:
    """Verify experiment tracking in execute()."""

    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_train_logs_experiment(self, mock_upload: MagicMock, tmp_path: Path):
        """TrainModel.execute() logs params to Vertex AI Experiments."""
        import sys

        import google.cloud

        mock_aip = MagicMock()
        token = "google.cloud.aiplatform"
        original_module = sys.modules.get(token)
        original_attr = getattr(google.cloud, "aiplatform", None)
        sys.modules[token] = mock_aip
        google.cloud.aiplatform = mock_aip
        try:
            model_dir = tmp_path / "artifacts"
            model_dir.mkdir()
            (model_dir / "model.pkl").write_bytes(b"fake")

            class _TestTrainer(TrainModel):
                def run(self) -> Path:
                    return model_dir

            trainer = _TestTrainer(
                experiment_name="test-exp",
                project="test-proj",
                region="us-east4",
                model_output_uri=str(tmp_path / "model"),
                output_uri_path=str(tmp_path / "output"),
            )
            trainer.execute()

            mock_aip.init.assert_called_once()
            mock_aip.start_run.assert_called_once()
            mock_aip.log_params.assert_called_once()
        finally:
            if original_module is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original_module
            if original_attr is not None:
                google.cloud.aiplatform = original_attr
            elif hasattr(google.cloud, "aiplatform"):
                delattr(google.cloud, "aiplatform")

    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_train_experiment_failure_non_fatal(self, mock_upload: MagicMock, tmp_path: Path):
        """Experiment tracking failure doesn't prevent training."""
        import sys

        import google.cloud

        mock_aip = MagicMock()
        mock_aip.init.side_effect = Exception("API error")
        token = "google.cloud.aiplatform"
        original_module = sys.modules.get(token)
        original_attr = getattr(google.cloud, "aiplatform", None)
        sys.modules[token] = mock_aip
        google.cloud.aiplatform = mock_aip
        try:

            class _TestTrainer(TrainModel):
                def run(self) -> None:
                    pass

            trainer = _TestTrainer(
                experiment_name="test-exp",
                project="test-proj",
                region="us-east4",
            )
            # Should not raise
            trainer.execute()
        finally:
            if original_module is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original_module
            if original_attr is not None:
                google.cloud.aiplatform = original_attr
            elif hasattr(google.cloud, "aiplatform"):
                delattr(google.cloud, "aiplatform")
