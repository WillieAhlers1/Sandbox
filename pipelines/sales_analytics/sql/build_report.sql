SELECT
    r.category,
    r.region,
    r.order_count,
    r.total_revenue,
    r.avg_order_value,
    COALESCE(s.total_stock, 0) AS total_stock,
    COALESCE(ref.refund_count, 0) AS refund_count,
    COALESCE(ref.total_refunds, 0) AS total_refunds
FROM `{bq_dataset}.agg_revenue` r
LEFT JOIN (
    SELECT
        category,
        SUM(total_stock) AS total_stock
    FROM `{bq_dataset}.stock_status`
    GROUP BY category
) s
    ON r.category = s.category
LEFT JOIN `{bq_dataset}.agg_refunds` ref
    ON r.category = ref.category
