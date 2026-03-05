SELECT
    o.category,
    COUNT(*) AS refund_count,
    SUM(ret.refund_amount) AS total_refunds,
    AVG(ret.refund_amount) AS avg_refund
FROM `{bq_dataset}.staged_returns` ret
JOIN `{bq_dataset}.staged_orders` o
    ON ret.order_id = o.order_id
GROUP BY o.category
