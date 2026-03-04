-- BigQuery: Raw events table creation
-- Naming: dsci-churn_prediction_new-raw-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.raw_events AS
SELECT
  CAST(FLOOR(1000 + RAND()*9000) AS STRING) AS user_id,
  CURRENT_TIMESTAMP() as event_timestamp,
  CASE FLOOR(RAND()*3)
    WHEN 0 THEN 'login'
    WHEN 1 THEN 'purchase'
    ELSE 'logout'
  END as event_type,
  CAST(FLOOR(RAND()*1000) AS STRING) AS session_id,
  CASE FLOOR(RAND()*3)
    WHEN 0 THEN 'mobile'
    WHEN 1 THEN 'desktop'
    ELSE 'tablet'
  END as device_type,
  CASE FLOOR(RAND()*5)
    WHEN 0 THEN 'US'
    WHEN 1 THEN 'UK'
    WHEN 2 THEN 'CA'
    WHEN 3 THEN 'AU'
    ELSE 'IN'
  END as country
FROM 
  UNNEST(GENERATE_ARRAY(1, 100)) AS n
WHERE
  CURRENT_TIMESTAMP() >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
