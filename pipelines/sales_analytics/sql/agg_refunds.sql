SELECT
    reason,
    COUNT(*) AS refund_count,
    SUM(refund_amount) AS total_refunds,
    AVG(refund_amount) AS avg_refund
FROM `{bq_dataset}.staged_returns`
GROUP BY reason
