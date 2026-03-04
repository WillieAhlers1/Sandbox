-- Feature Store: User entity definition
-- Entity: fs_dsci_churn_prediction_new_user_main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${bq_dataset}`.entity_user AS
SELECT DISTINCT
  user_id as entity_id,
  CURRENT_TIMESTAMP() as created_timestamp
FROM
  `${bq_dataset}`.raw_events
