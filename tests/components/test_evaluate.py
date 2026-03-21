"""Unit tests for EvaluateModel (gcp_ml_framework.components.ml.evaluate)."""

from __future__ import annotations

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
