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
        assert tm.trainer_args == []
        assert tm.hyperparameters == {}
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
    def test_train_model_execute_creates_temp_dir(self, mock_upload: MagicMock):
        """execute() creates a temp dir, calls run(), and uploads files via upload_file."""

        work_dir_seen: list[str] = []

        class _TestTrainer(TrainModel):
            def run(self) -> None:
                # Record the work dir that execute() set up
                work_dir_seen.append(self._work_dir)
                # Write a dummy model file so upload_file gets called
                (Path(self._work_dir) / "model.pkl").write_text("fake-model")

        trainer = _TestTrainer(
            model_output_uri="gs://bucket/models/test",
            project="test-project",
        )
        trainer.execute()

        # run() was called and received a valid temp dir
        assert len(work_dir_seen) == 1
        assert work_dir_seen[0] != ""
        # upload_file was called for our model file
        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        assert str(call_args[0][0]).endswith("model.pkl")
        assert "gs://bucket/models/test" in call_args[0][1]

    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_train_model_writes_output_uri(self, mock_upload: MagicMock, tmp_path: Path):
        """execute() writes model_output_uri to the output_uri_path file."""
        output_file = tmp_path / "output" / "uri"

        class _TestTrainer(TrainModel):
            def run(self) -> None:
                pass  # no-op; we only care about the output URI writing

        trainer = _TestTrainer(
            model_output_uri="gs://bucket/models/churn/latest",
            output_uri_path=str(output_file),
        )
        trainer.execute()

        assert output_file.exists()
        assert output_file.read_text() == "gs://bucket/models/churn/latest"
