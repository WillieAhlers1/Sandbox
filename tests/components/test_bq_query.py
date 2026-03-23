"""Unit tests for BQQuery component (gcp_ml_framework.components.operators.bq_query)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation and task type
# ---------------------------------------------------------------------------


class TestBQQueryBasics:
    def test_is_task_type(self):
        assert BQQuery.task_type == TaskType.TASK

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


# ---------------------------------------------------------------------------
# Output tracking (5.14)
# ---------------------------------------------------------------------------


class TestBQQueryOutputTracking:
    """BQQuery.execute() writes destination table to output_uri_path."""

    def test_writes_output_uri_path(self, tmp_path):
        """execute() writes {project}.{dataset}.{destination_table} to output_uri_path."""
        mock_bq = MagicMock()
        token = "google.cloud.bigquery"
        original = sys.modules.get(token)
        sys.modules[token] = mock_bq
        try:
            output_file = tmp_path / "output" / "uri"
            bq = BQQuery(
                sql="SELECT 1",
                destination_table="my_output",
                project="test-project",
                dataset="test_dataset",
                output_uri_path=str(output_file),
            )
            bq.execute()

            assert output_file.exists()
            assert output_file.read_text() == "test-project.test_dataset.my_output"
        finally:
            if original is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original

    def test_no_output_without_destination(self, tmp_path):
        """execute() does NOT write output_uri_path when no destination_table."""
        mock_bq = MagicMock()
        token = "google.cloud.bigquery"
        original = sys.modules.get(token)
        sys.modules[token] = mock_bq
        try:
            output_file = tmp_path / "output" / "uri"
            bq = BQQuery(
                sql="SELECT 1",
                project="test-project",
                dataset="test_dataset",
                output_uri_path=str(output_file),
            )
            bq.execute()

            assert not output_file.exists()
        finally:
            if original is None:
                sys.modules.pop(token, None)
            else:
                sys.modules[token] = original


# ---------------------------------------------------------------------------
# Template fields (gcs_prefix, namespace must be real fields)
# ---------------------------------------------------------------------------


class TestBQQueryTemplateFields:
    def test_has_template_fields(self):
        """BQQuery must have gcs_prefix and namespace as real Pydantic fields."""
        assert "gcs_prefix" in BQQuery.model_fields, "gcs_prefix not a BQQuery field"
        assert "namespace" in BQQuery.model_fields, "namespace not a BQQuery field"

    def test_template_fields_default_empty(self):
        """gcs_prefix and namespace default to empty string."""
        bq = BQQuery(sql="SELECT 1")
        assert bq.gcs_prefix == ""
        assert bq.namespace == ""

    def test_execute_no_getattr_fallback(self):
        """execute() must use self.field directly, not getattr fallback."""
        import inspect

        src = inspect.getsource(BQQuery.execute)
        assert "getattr" not in src, "execute() still uses getattr fallback instead of real fields"
