-- BigQuery: Raw user features
-- Naming: dsci-churn_prediction-user-features-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.raw_user_features AS
SELECT
  CAST(FLOOR(1000 + RAND()*9000) AS STRING) AS entity_id,
  CAST(FLOOR(RAND()*10) AS INT64) AS session_count_7d,
  CAST(FLOOR(RAND()*30) AS INT64) AS session_count_30d,
  CAST(FLOOR(RAND()*50) AS INT64) AS total_purchases_30d,
  CAST(FLOOR(RAND()*60) AS INT64) AS days_since_last_login,
  CAST(FLOOR(RAND()*5) AS INT64) AS support_tickets_90d,
  CAST(RAND()*3600 AS FLOAT64) AS avg_session_duration_s,
  CAST(FLOOR(RAND()*2) AS BOOLEAN) AS churned_within_30d,
  DATE_SUB(CURRENT_DATE(), INTERVAL CAST(FLOOR(RAND()*30) AS INT64) DAY) AS event_date
FROM UNNEST(GENERATE_ARRAY(1, 1000)) AS n
