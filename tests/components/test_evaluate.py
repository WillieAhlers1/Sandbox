"""Unit tests for EvaluateModel (gcp_ml_framework.components.ml.evaluate)."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.evaluate import EvaluateModel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestEvaluateModelInstantiation:
    """Verify EvaluateModel fields and defaults."""

    def test_evaluate_model_instantiation(self):
        """EvaluateModel has dataset_uri, model_uri, metrics, gate fields."""
        em = EvaluateModel()
        assert isinstance(em, BaseComponent)
        assert em.dataset_uri == ""
        assert em.model_uri == ""
        assert em.experiment_name == ""
        assert isinstance(em.metrics, list)
        assert isinstance(em.gate, dict)
        assert em.component_name == "evaluate_model"

    def test_evaluate_model_default_metrics(self):
        """metrics defaults to ["auc"]."""
        em = EvaluateModel()
        assert em.metrics == ["auc"]


# ---------------------------------------------------------------------------
# execute() delegation
# ---------------------------------------------------------------------------


class TestEvaluateModelExecute:
    """Verify execute() delegates to utils.evaluate.run_evaluate with correct args."""

    @patch("gcp_ml_framework.utils.evaluate.run_evaluate")
    def test_evaluate_model_execute_delegates(self, mock_run_evaluate: MagicMock):
        """execute() calls run_evaluate() with the component's field values."""
        em = EvaluateModel(
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            dataset_uri="gs://bucket/eval_data",
            metrics=["auc", "f1"],
            gate={"auc": 0.8},
            experiment_name="exp-001",
            output_uri_path="/tmp/output_uri",
        )
        em.execute()

        mock_run_evaluate.assert_called_once_with(
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            eval_dataset_uri="gs://bucket/eval_data",
            metrics=["auc", "f1"],
            gate={"auc": 0.8},
            experiment_name="exp-001",
            output_uri_path="/tmp/output_uri",
        )


# ---------------------------------------------------------------------------
# execute()→run() lifecycle
# ---------------------------------------------------------------------------


class TestEvaluateModelLifecycle:
    """Verify execute()→run() lifecycle."""

    @patch("gcp_ml_framework.utils.evaluate.run_evaluate")
    def test_execute_calls_run(self, mock_run_evaluate: MagicMock):
        """execute() should delegate to run(), not call utility directly."""
        em = EvaluateModel(
            project="test-project",
            region="us-central1",
        )
        with patch.object(EvaluateModel, "run") as mock_run:
            em.execute()
            mock_run.assert_called_once()

    @patch("gcp_ml_framework.utils.evaluate.run_evaluate")
    def test_subclass_run_override(self, mock_run_evaluate: MagicMock):
        """Data scientist subclass overriding run() should have custom code execute."""
        class CustomEval(EvaluateModel):
            def run(self) -> None:
                self._custom_called = True

        ce = CustomEval(project="test-project", region="us-central1")
        ce.execute()
        assert ce._custom_called is True
        mock_run_evaluate.assert_not_called()


# ---------------------------------------------------------------------------
# Experiment tracking (5.4)
# ---------------------------------------------------------------------------


class TestEvaluateModelExperiments:
    """Verify experiment tracking in execute()."""

    def test_evaluate_logs_metrics_to_experiment(self, tmp_path):
        """EvaluateModel.execute() logs metrics to Vertex AI Experiments."""
        import google.cloud

        mock_aip = MagicMock()
        token = "google.cloud.aiplatform"
        original_module = sys.modules.get(token)
        original_attr = getattr(google.cloud, "aiplatform", None)
        sys.modules[token] = mock_aip
        google.cloud.aiplatform = mock_aip
        try:
            # Write fake metrics file for execute() to read
            output_file = tmp_path / "metrics.json"
            output_file.write_text(json.dumps({"rmse": 42.0, "r2": 0.95}))

            class _NoOpEval(EvaluateModel):
                def run(self) -> None:
                    pass  # skip actual evaluation

            em = _NoOpEval(
                experiment_name="test-exp",
                project="test-proj",
                region="us-east4",
                run_date="2026-03-21",
                output_uri_path=str(output_file),
            )
            em.execute()

            mock_aip.init.assert_called_once()
            mock_aip.start_run.assert_called_once_with(
                run="train-2026-03-21", resume=True
            )
            mock_aip.log_metrics.assert_called_once_with(
                {"rmse": 42.0, "r2": 0.95}
            )
        finally:
            if original_module is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original_module
            if original_attr is not None:
                google.cloud.aiplatform = original_attr
            elif hasattr(google.cloud, "aiplatform"):
                delattr(google.cloud, "aiplatform")

    def test_evaluate_experiment_failure_non_fatal(self, tmp_path):
        """Experiment tracking failure doesn't prevent evaluation."""
        import google.cloud

        mock_aip = MagicMock()
        mock_aip.init.side_effect = Exception("API error")
        token = "google.cloud.aiplatform"
        original_module = sys.modules.get(token)
        original_attr = getattr(google.cloud, "aiplatform", None)
        sys.modules[token] = mock_aip
        google.cloud.aiplatform = mock_aip
        try:
            class _NoOpEval(EvaluateModel):
                def run(self) -> None:
                    pass

            em = _NoOpEval(
                experiment_name="test-exp",
                project="test-proj",
                region="us-east4",
            )
            # Should not raise
            em.execute()
        finally:
            if original_module is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original_module
            if original_attr is not None:
                google.cloud.aiplatform = original_attr
            elif hasattr(google.cloud, "aiplatform"):
                delattr(google.cloud, "aiplatform")
