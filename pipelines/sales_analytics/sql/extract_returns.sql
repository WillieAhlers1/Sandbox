SELECT
    return_id,
    order_id,
    reason,
    refund_amount,
    return_date
FROM `{bq_dataset}.raw_returns`
WHERE return_date = '{run_date}'
