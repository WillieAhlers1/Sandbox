SELECT
    order_id,
    customer_id,
    category,
    amount,
    region,
    order_date
FROM `{bq_dataset}.raw_orders`
WHERE order_date = '{run_date}'
