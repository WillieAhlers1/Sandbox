"""Unit tests for BQQuery component (gcp_ml_framework.components.operators.bq_query)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation and task type
# ---------------------------------------------------------------------------


class TestBQQueryBasics:
    def test_is_task_type(self):
        assert BQQuery._task_type == TaskType.TASK

    def test_instantiation_with_sql(self):
        bq = BQQuery(sql="SELECT 1")
        assert bq.sql == "SELECT 1"
        assert bq.component_name == "bq_query"

    def test_instantiation_with_sql_file(self):
        bq = BQQuery(sql_file="sql/query.sql")
        assert bq.sql_file == "sql/query.sql"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestBQQueryValidation:
    def test_requires_sql_source(self):
        """Must provide either sql or sql_file."""
        with pytest.raises(ValueError, match="requires either sql or sql_file"):
            BQQuery()

    def test_mutually_exclusive(self):
        """Cannot provide both sql and sql_file."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            BQQuery(sql="SELECT 1", sql_file="query.sql")


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------


class TestBQQueryResolve:
    def test_resolve_sql(self, mock_context):
        bq = BQQuery(sql="SELECT * FROM `{bq_dataset}.table` WHERE dt = '{run_date}'")
        resolved = bq.resolve_sql(mock_context)
        assert mock_context.bq_dataset in resolved
        assert "{{ ds }}" in resolved
        assert "{run_date}" not in resolved

    def test_resolve_destination(self, mock_context):
        bq = BQQuery(sql="SELECT 1", destination_table="output_table")
        dest = bq.resolve_destination(mock_context)
        assert dest is not None
        assert dest["tableId"] == "output_table"
        assert dest["datasetId"] == mock_context.bq_dataset

    def test_resolve_destination_none(self, mock_context):
        bq = BQQuery(sql="SELECT 1")
        assert bq.resolve_destination(mock_context) is None
