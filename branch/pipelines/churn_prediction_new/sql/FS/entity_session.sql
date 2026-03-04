-- Feature Store: Session entity definition
-- Entity: fs_dsci_churn_prediction_new_session_main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.entity_session AS
SELECT DISTINCT
  session_id as entity_id,
  CURRENT_TIMESTAMP() as created_timestamp
FROM
  `${bq_dataset}`.raw_events
