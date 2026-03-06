"""
Sales analytics DAG — non-linear fan-out / fan-in pattern.

DAG shape:
    extract_orders ────→ agg_revenue ────→┐
    extract_orders ──┬─→ agg_refunds ───→├→ build_report → notify
    extract_returns ─┘                   │
    extract_inventory ─→ check_stock ───→┘
"""

from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(
        name="sales_analytics",
        schedule="0 8 * * *",  # every day at 08:00 UTC
        description="Daily sales analytics with fan-out/fan-in pattern",
        tags=["analytics", "sales"],
    )
    # --- Fan-out: 3 parallel extractions ---
    .task(
        BQQueryTask(sql_file="sql/extract_orders.sql", destination_table="staged_orders"),
        name="extract_orders",
        depends_on=[],
    )
    .task(
        BQQueryTask(sql_file="sql/extract_inventory.sql", destination_table="staged_inventory"),
        name="extract_inventory",
        depends_on=[],
    )
    .task(
        BQQueryTask(sql_file="sql/extract_returns.sql", destination_table="staged_returns"),
        name="extract_returns",
        depends_on=[],
    )
    # --- Aggregations: each depends on its extraction ---
    .task(
        BQQueryTask(sql_file="sql/agg_revenue.sql", destination_table="agg_revenue"),
        name="agg_revenue",
        depends_on=["extract_orders"],
    )
    .task(
        BQQueryTask(sql_file="sql/check_stock.sql", destination_table="stock_status"),
        name="check_stock",
        depends_on=["extract_inventory"],
    )
    .task(
        BQQueryTask(sql_file="sql/agg_refunds.sql", destination_table="agg_refunds"),
        name="agg_refunds",
        depends_on=["extract_returns", "extract_orders"],
    )
    # --- Fan-in: build_report depends on all 3 aggregations ---
    .task(
        BQQueryTask(sql_file="sql/build_report.sql", destination_table="daily_report"),
        name="build_report",
        depends_on=["agg_revenue", "check_stock", "agg_refunds"],
    )
    # --- Notification ---
    .task(
        EmailTask(
            to=["analytics-team@company.com"],
            subject="[{namespace}] Daily Sales Report — {run_date}",
            body=(
                "The daily sales analytics pipeline has completed.\n\n"
                "Report table: {bq_dataset}.daily_report\n"
                "Execution date: {run_date}"
            ),
        ),
        name="notify",
    )
    .build()
)
