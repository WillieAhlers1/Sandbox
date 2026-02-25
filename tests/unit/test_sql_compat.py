"""Unit tests for utils/sql_compat.py — BigQuery → DuckDB SQL translations."""

from gcp_ml_framework.utils.sql_compat import bq_to_duckdb


class TestBqToDuckdb:
    def test_backtick_identifiers(self):
        assert bq_to_duckdb("`ds.table`") == '"ds"."table"'

    def test_date_sub(self):
        result = bq_to_duckdb("DATE_SUB('2024-01-01', INTERVAL 90 DAY)")
        assert "CAST" in result
        assert "INTERVAL 90 DAY" in result

    def test_safe_divide(self):
        result = bq_to_duckdb("SAFE_DIVIDE(a, b)")
        assert "CASE WHEN" in result

    def test_safe_divide_with_nullif(self):
        result = bq_to_duckdb("SAFE_DIVIDE(x, NULLIF(y, 0))")
        assert "CASE WHEN" in result
        assert "NULLIF" in result

    def test_log1p(self):
        assert bq_to_duckdb("LOG1P(x)") == "LN(1 + (x))"

    def test_current_timestamp(self):
        assert bq_to_duckdb("CURRENT_TIMESTAMP()") == "now()"

    def test_current_timestamp_case_insensitive(self):
        assert bq_to_duckdb("current_timestamp()") == "now()"

    def test_current_timestamp_in_select(self):
        sql = "SELECT id, CURRENT_TIMESTAMP() AS ts FROM t"
        result = bq_to_duckdb(sql)
        assert "now()" in result
        assert "CURRENT_TIMESTAMP" not in result

    def test_cast_float64_to_double(self):
        assert bq_to_duckdb("CAST(x AS FLOAT64)") == "CAST(x AS DOUBLE)"

    def test_passthrough_plain_sql(self):
        sql = "SELECT 1"
        assert bq_to_duckdb(sql) == sql
