-- BigQuery: Behavior features
-- Naming: dsci-churn_prediction_new-behavior-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.features_behavior AS
SELECT
  user_id,
  COUNTIF(event_type = 'login') as login_count,
  COUNTIF(event_type = 'purchase') as purchase_count,
  SAFE_DIVIDE(COUNTIF(event_type = 'purchase'), COUNT(*)) as purchase_rate,
  COUNT(DISTINCT device_type) as device_diversity,
  CASE 
    WHEN COUNT(DISTINCT device_type) >= 3 THEN 'high_engagement'
    WHEN COUNT(DISTINCT device_type) >= 2 THEN 'medium_engagement'
    ELSE 'low_engagement'
  END as engagement_segment
FROM
  `${bq_dataset}`.raw_events
GROUP BY
  user_id
