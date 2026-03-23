"""Unit tests for DBTRun component."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.transformation.dbt_run import DBTRun
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestDBTRunBasics:
    def test_is_task_type(self):
        assert DBTRun.task_type == TaskType.TASK

    def test_instantiation(self):
        dbt = DBTRun()
        assert isinstance(dbt, BaseComponent)
        assert dbt.project_dir == "/dbt"
        assert dbt.target == "dev"
        assert dbt.models == ""
        assert dbt.dbt_vars == ""
        assert dbt.component_name == "dbt_run"


class TestDBTRunRenderOperator:
    def test_renders_bash_operator(self, mock_context):
        dbt = DBTRun()
        code, imports = dbt.render_operator(mock_context)
        assert "BashOperator" in code
        assert "dbt run" in code
        assert any("BashOperator" in imp for imp in imports)

    def test_includes_models_flag(self, mock_context):
        dbt = DBTRun(models="marts.finance")
        code, imports = dbt.render_operator(mock_context)
        assert "--models marts.finance" in code

    def test_includes_vars_flag(self, mock_context):
        dbt = DBTRun(dbt_vars='{"date": "2026-01-01"}')
        code, imports = dbt.render_operator(mock_context)
        assert "--vars" in code

    def test_includes_target(self, mock_context):
        dbt = DBTRun(target="staging")
        code, imports = dbt.render_operator(mock_context)
        assert "--target staging" in code


class TestDBTRunMainBlock:
    def test_has_main_block(self):
        import ast

        with open("gcp_ml_framework/components/transformation/dbt_run.py") as f:
            tree = ast.parse(f.read())
        has_main = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and any(
                isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators
            )
            for node in ast.walk(tree)
        )
        assert has_main, "dbt_run.py missing __main__ block"
