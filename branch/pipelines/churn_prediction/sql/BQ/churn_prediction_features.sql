-- BigQuery: Churn prediction features
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.churn_prediction_features AS

WITH base AS (
  SELECT *
  FROM `${bq_dataset}`.raw_events
  WHERE DATE(event_timestamp) = '${run_date}'
),

aggregated AS (
  SELECT
    user_id,
    COUNT(*) AS total_events,
    COUNTIF(event_type = 'login') AS login_events,
    COUNTIF(event_type = 'purchase') AS purchase_events,
    COUNT(DISTINCT session_id) AS session_count,
    MAX(event_timestamp) AS last_event_time
  FROM base
  GROUP BY user_id
),

labeled AS (
  SELECT
    *,
    CASE
      WHEN total_events < 3 AND login_events < 2 THEN 1
      ELSE 0
    END AS is_churned
  FROM aggregated
)

SELECT *
FROM labeled
