"""BigQuery → DuckDB SQL compatibility shims for local_run()."""

from __future__ import annotations

import re

# Pattern fragment that matches a SQL expression which may contain nested
# parenthesised sub-expressions (one level deep).  This avoids the classic
# `.+?` trap where a closing paren inside e.g. ``NULLIF(x, 0)`` is consumed
# too early.
_EXPR = r"(?:[^(),]*(?:\([^()]*\))?[^(),]*)"


def bq_to_duckdb(sql: str) -> str:
    """Rewrite common BigQuery SQL idioms to DuckDB-compatible equivalents.

    Transformations applied (in order):
    1. Backtick identifiers `` `schema.table` `` → ``"schema"."table"``
    2. ``DATE_SUB(expr, INTERVAL n unit)`` → ``(CAST(expr AS DATE) - INTERVAL n unit)``
    3. ``DATE_ADD(expr, INTERVAL n unit)`` → ``(CAST(expr AS DATE) + INTERVAL n unit)``
    4. ``SAFE_DIVIDE(a, b)`` → ``(CASE WHEN (b) = 0 THEN NULL ELSE (a) / (b) END)``
    5. ``LOG1P(x)`` → ``LN(1 + (x))``
    6. ``CAST(... AS FLOAT64)`` → ``CAST(... AS DOUBLE)``
    7. ``CURRENT_TIMESTAMP()`` → ``now()``
    """

    # 1. Backtick-quoted identifiers → double-quoted, splitting on dots
    sql = re.sub(
        r"`([^`]+)`",
        lambda m: ".".join(f'"{p}"' for p in m.group(1).split(".")),
        sql,
    )

    # 2. DATE_SUB(expr, INTERVAL n unit)
    sql = re.sub(
        r"DATE_SUB\(\s*(.+?)\s*,\s*(INTERVAL\s+\d+\s+\w+)\s*\)",
        r"(CAST(\1 AS DATE) - \2)",
        sql,
        flags=re.IGNORECASE,
    )

    # 3. DATE_ADD(expr, INTERVAL n unit)
    sql = re.sub(
        r"DATE_ADD\(\s*(.+?)\s*,\s*(INTERVAL\s+\d+\s+\w+)\s*\)",
        r"(CAST(\1 AS DATE) + \2)",
        sql,
        flags=re.IGNORECASE,
    )

    # 4. SAFE_DIVIDE(a, b) — use _EXPR to handle nested parens like NULLIF(x, 0)
    sql = re.sub(
        rf"SAFE_DIVIDE\(\s*({_EXPR})\s*,\s*({_EXPR})\s*\)",
        r"(CASE WHEN (\2) = 0 THEN NULL ELSE (\1) / (\2) END)",
        sql,
        flags=re.IGNORECASE,
    )

    # 5. LOG1P(x) — use _EXPR to handle nested parens
    sql = re.sub(
        rf"LOG1P\(\s*({_EXPR})\s*\)",
        r"LN(1 + (\1))",
        sql,
        flags=re.IGNORECASE,
    )

    # 6. CAST(... AS FLOAT64) → CAST(... AS DOUBLE)
    sql = re.sub(
        r"\bAS\s+FLOAT64\b",
        "AS DOUBLE",
        sql,
        flags=re.IGNORECASE,
    )

    # 7. CURRENT_TIMESTAMP() → now()
    sql = re.sub(
        r"CURRENT_TIMESTAMP\(\s*\)",
        "now()",
        sql,
        flags=re.IGNORECASE,
    )

    return sql
