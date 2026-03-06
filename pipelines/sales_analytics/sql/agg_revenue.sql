SELECT
    category,
    region,
    COUNT(*) AS order_count,
    SUM(amount) AS total_revenue,
    AVG(amount) AS avg_order_value
FROM `{bq_dataset}.staged_orders`
GROUP BY category, region
ORDER BY total_revenue DESC
