"""Verify house_price pipeline imports resolve correctly."""

import pytest

pytestmark = pytest.mark.unit


def test_house_price_step_imports():
    """house_price training step must import from second_run, not third_run."""
    from pipelines.house_price.steps.train_regression_model import HouseTrainModelStep

    assert HouseTrainModelStep is not None


def test_second_run_estimator_importable():
    """second_run.estimator must be importable (not third_run)."""
    from second_run.estimator import HousePredictionModel

    assert HousePredictionModel is not None
