-- BigQuery: Engagement features
-- Naming: dsci-churn_prediction_new-features-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.features_engagement AS
SELECT
  user_id,
  COUNT(DISTINCT DATE(event_timestamp)) as active_days,
  COUNT(*) as total_events,
  COUNT(DISTINCT session_id) as session_count,
  DATE_DIFF(CURRENT_DATE(), MAX(DATE(event_timestamp)), DAY) as days_since_activity,
  COUNTIF(DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) > 0 as active_last_7d,
  COUNTIF(DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)) > 0 as active_last_14d
FROM
  `${bq_dataset}`.raw_events
GROUP BY
  user_id
