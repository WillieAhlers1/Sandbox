"""Unit tests for BQTransform (gcp_ml_framework.components.transformation.bq_transform)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestBQTransformBasics:
    def test_is_task_type(self):
        assert BQTransform._task_type == TaskType.TASK

    def test_instantiation(self):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        assert bt.output_table == "features"
        assert bt.component_name == "bq_transform"

    def test_requires_sql_source(self):
        with pytest.raises(ValueError, match="sql_file or sql"):
            BQTransform(output_table="features")


class TestBQTransformRenderOperator:
    def test_has_render_operator(self):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        assert hasattr(bt, "render_operator")
        assert callable(bt.render_operator)

    def test_returns_bq_operator(self, mock_context):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context)
        assert "BigQueryInsertJobOperator" in code
        assert any("BigQueryInsertJobOperator" in imp for imp in imports)

    def test_resolves_templates(self, mock_context):
        bt = BQTransform(
            output_table="features",
            sql="SELECT * FROM `{bq_dataset}.raw_data`",
        )
        code, imports = bt.render_operator(mock_context)
        assert mock_context.bq_dataset in code
        assert "{bq_dataset}" not in code

    def test_includes_destination(self, mock_context):
        bt = BQTransform(output_table="my_table", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context)
        assert "my_table" in code
        assert "destinationTable" in code

    def test_accepts_pipeline_dir_kwarg(self, mock_context):
        """render_operator() must accept pipeline_dir kwarg (SmartCompiler passes it)."""
        bt = BQTransform(output_table="features", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context, pipeline_dir=None)
        assert "BigQueryInsertJobOperator" in code

    def test_run_date_becomes_jinja(self, mock_context):
        bt = BQTransform(
            output_table="features",
            sql="SELECT * WHERE date = '{run_date}'",
        )
        code, imports = bt.render_operator(mock_context)
        assert "{{ ds }}" in code
        assert "{run_date}" not in code
