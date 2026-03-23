"""Unit tests for run_evaluate() regression and classification support."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_gcp():
    """Inject mocks for google.cloud.bigquery and google.cloud.storage."""
    import google.cloud

    mock_bq = MagicMock()
    mock_storage = MagicMock()
    originals = {}
    original_attrs = {}
    for token, mock, attr_name in [
        ("google.cloud.bigquery", mock_bq, "bigquery"),
        ("google.cloud.storage", mock_storage, "storage"),
    ]:
        originals[token] = sys.modules.get(token)
        original_attrs[attr_name] = getattr(google.cloud, attr_name, None)
        sys.modules[token] = mock
        setattr(google.cloud, attr_name, mock)
    yield mock_bq, mock_storage
    for token, original in originals.items():
        if original is None:
            sys.modules.pop(token, None)
        else:
            sys.modules[token] = original
    for attr_name, original_attr in original_attrs.items():
        if original_attr is not None:
            setattr(google.cloud, attr_name, original_attr)
        elif hasattr(google.cloud, attr_name):
            delattr(google.cloud, attr_name)


def _make_mock_model(*, is_classifier: bool):
    """Create a mock sklearn-like model."""
    model = MagicMock()
    if is_classifier:
        model.predict_proba = MagicMock(return_value=np.array([[0.2, 0.8], [0.7, 0.3], [0.1, 0.9]]))
    else:
        del model.predict_proba
        model.predict = MagicMock(return_value=np.array([100.0, 200.0, 300.0]))
    return model


def _make_dataframe_model():
    """Create a model that returns a DataFrame from predict()."""
    import pandas as pd

    model = MagicMock()
    del model.predict_proba
    model.predict = MagicMock(
        return_value=pd.DataFrame(
            {
                "price": [100.0, 200.0, 300.0],
                "is_valid": [True, True, True],
                "info": [None, None, None],
            }
        )
    )
    return model


class TestRegressionMetrics:
    """run_evaluate() computes regression metrics for regression models."""

    def test_regression_computes_rmse_mae_r2(self, mock_gcp, tmp_path):
        """Regression model computes rmse, mae, r2."""
        import pandas as pd

        from gcp_ml_framework.utils.evaluate import run_evaluate

        mock_bq, mock_storage = mock_gcp
        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        df = pd.DataFrame(
            {
                "price": [100.0, 200.0, 300.0],
                "area": [1000, 2000, 3000],
            }
        )
        mock_client.query.return_value.to_dataframe.return_value = df

        model = _make_mock_model(is_classifier=False)
        model.predict.return_value = np.array([110.0, 190.0, 310.0])
        mock_blob = MagicMock()
        mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

        output_file = tmp_path / "metrics.json"

        with patch("gcp_ml_framework.utils.evaluate.pickle") as mock_pickle:
            mock_pickle.load.return_value = model
            run_evaluate(
                project="test-proj",
                region="us-east4",
                model_uri="gs://bucket/models/v1",
                eval_dataset_uri="project.dataset.table",
                metrics=["rmse", "mae", "r2"],
                gate={},
                experiment_name="test-exp",
                output_uri_path=str(output_file),
            )

        assert output_file.exists()
        result = json.loads(output_file.read_text())
        assert "rmse" in result
        assert "mae" in result
        assert "r2" in result
        assert isinstance(result["rmse"], float)

    def test_classification_still_works(self, mock_gcp, tmp_path):
        """Classification model still computes auc, f1."""
        import pandas as pd

        from gcp_ml_framework.utils.evaluate import run_evaluate

        mock_bq, mock_storage = mock_gcp
        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        df = pd.DataFrame(
            {
                "label": [1, 0, 1],
                "feature_a": [0.5, 0.3, 0.8],
            }
        )
        mock_client.query.return_value.to_dataframe.return_value = df

        model = _make_mock_model(is_classifier=True)
        mock_blob = MagicMock()
        mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

        output_file = tmp_path / "metrics.json"

        with patch("gcp_ml_framework.utils.evaluate.pickle") as mock_pickle:
            mock_pickle.load.return_value = model
            run_evaluate(
                project="test-proj",
                region="us-east4",
                model_uri="gs://bucket/models/v1",
                eval_dataset_uri="project.dataset.table",
                metrics=["auc", "f1"],
                gate={},
                experiment_name="test-exp",
                output_uri_path=str(output_file),
            )

        result = json.loads(output_file.read_text())
        assert "auc" in result
        assert "f1" in result

    def test_dataframe_predictions_handled(self, mock_gcp, tmp_path):
        """Model returning DataFrame predictions is handled correctly."""
        import pandas as pd

        from gcp_ml_framework.utils.evaluate import run_evaluate

        mock_bq, mock_storage = mock_gcp
        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        df = pd.DataFrame(
            {
                "price": [100.0, 200.0, 300.0],
                "area": [1000, 2000, 3000],
            }
        )
        mock_client.query.return_value.to_dataframe.return_value = df

        model = _make_dataframe_model()
        mock_blob = MagicMock()
        mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

        output_file = tmp_path / "metrics.json"

        with patch("gcp_ml_framework.utils.evaluate.pickle") as mock_pickle:
            mock_pickle.load.return_value = model
            run_evaluate(
                project="test-proj",
                region="us-east4",
                model_uri="gs://bucket/models/v1",
                eval_dataset_uri="project.dataset.table",
                metrics=["rmse", "mae", "r2"],
                gate={},
                experiment_name="test-exp",
                output_uri_path=str(output_file),
            )

        result = json.loads(output_file.read_text())
        assert "rmse" in result


class TestGateCheck:
    """Gate checks work for both regression and classification."""

    def test_regression_gate_lower_is_better(self, mock_gcp, tmp_path):
        """For rmse/mae, lower is better — fail if above threshold."""
        import pandas as pd

        from gcp_ml_framework.utils.evaluate import run_evaluate

        mock_bq, mock_storage = mock_gcp
        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        df = pd.DataFrame(
            {
                "price": [100.0, 200.0, 300.0],
                "area": [1000, 2000, 3000],
            }
        )
        mock_client.query.return_value.to_dataframe.return_value = df

        model = _make_mock_model(is_classifier=False)
        model.predict.return_value = np.array([1e6, 2e6, 3e6])
        mock_blob = MagicMock()
        mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

        with patch("gcp_ml_framework.utils.evaluate.pickle") as mock_pickle:
            mock_pickle.load.return_value = model
            with pytest.raises(ValueError, match="failed evaluation gates"):
                run_evaluate(
                    project="test-proj",
                    region="us-east4",
                    model_uri="gs://bucket/models/v1",
                    eval_dataset_uri="project.dataset.table",
                    metrics=["rmse"],
                    gate={"rmse": 100.0},
                    experiment_name="test-exp",
                    output_uri_path=str(tmp_path / "out"),
                )
