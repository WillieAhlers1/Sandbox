"""Unit tests for WriteFeatures (gcp_ml_framework.components.feature_store.write_features)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestWriteFeaturesBasics:
    def test_is_task_type(self):
        assert WriteFeatures.task_type == TaskType.TASK

    def test_instantiation(self):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        assert wf.entity == "user"
        assert wf.feature_group == "churn_signals"


class TestWriteFeaturesRenderOperator:
    def test_has_render_operator(self):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        assert hasattr(wf, "render_operator")
        assert callable(wf.render_operator)

    def test_returns_python_operator(self, mock_context):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        code, imports = wf.render_operator(mock_context)
        assert "PythonOperator" in code
        assert any("PythonOperator" in imp for imp in imports)

    def test_accepts_pipeline_dir_kwarg(self, mock_context):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        code, imports = wf.render_operator(mock_context, pipeline_dir=None)
        assert "PythonOperator" in code

    def test_render_operator_defines_callable(self, mock_context):
        """render_operator() must define the python_callable function."""
        wf = WriteFeatures(entity="user", feature_group="churn")
        code, imports = wf.render_operator(mock_context)
        assert "def _write_features_" in code, (
            "render_operator doesn't define the callable function"
        )
