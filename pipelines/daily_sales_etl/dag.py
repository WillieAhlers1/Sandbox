"""
Daily sales ETL — extract orders, compute revenue summary, notify team.

This is a pure data engineering DAG. No ML, no Vertex AI.
The framework handles BQ operator creation, naming, and Composer deployment.
"""

from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

dag = (
    DAGBuilder(
        name="daily_sales_etl",
        schedule="30 7 * * *",  # every day at 07:30 UTC
        description="Daily sales data extraction and transformation",
        tags=["etl", "sales"],
    )
    .task(
        BQQueryTask(
            sql="""
                SELECT
                    order_id,
                    customer_id,
                    product_category,
                    order_amount,
                    order_date,
                    region
                FROM `{bq_dataset}.raw_orders`
                WHERE order_date = '{run_date}'
            """,
            destination_table="staged_orders",
        ),
        name="extract_raw_orders",
    )
    .task(
        BQQueryTask(
            sql="""
                SELECT
                    order_date,
                    product_category,
                    region,
                    COUNT(*) AS order_count,
                    SUM(order_amount) AS total_revenue,
                    AVG(order_amount) AS avg_order_value
                FROM `{bq_dataset}.staged_orders`
                GROUP BY order_date, product_category, region
                ORDER BY total_revenue DESC
            """,
            destination_table="daily_revenue_summary",
        ),
        name="transform_daily_summary",
    )
    .task(
        EmailTask(
            to=["data-team@company.com"],
            subject="[{namespace}] Daily Sales ETL Complete — {run_date}",
            body=(
                "The daily sales ETL pipeline has completed successfully.\n\n"
                "Summary table: {bq_dataset}.daily_revenue_summary\n"
                "Execution date: {run_date}\n"
                "Namespace: {namespace}"
            ),
        ),
        name="notify_team",
    )
    .build()
)
