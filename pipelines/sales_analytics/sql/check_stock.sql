SELECT
    category,
    warehouse,
    SUM(stock_count) AS total_stock,
    CASE
        WHEN SUM(stock_count) < 10 THEN 'LOW'
        WHEN SUM(stock_count) < 50 THEN 'MEDIUM'
        ELSE 'HIGH'
    END AS stock_level
FROM `{bq_dataset}.staged_inventory`
GROUP BY category, warehouse
