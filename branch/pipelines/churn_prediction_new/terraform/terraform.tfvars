# Auto-generated Terraform variables (from framework.yaml)
# Provisioning: BigQuery, SQL execution, Docker build, Artifact Registry

project_id                = "prj-0n-dta-pt-ai-sandbox"
region                    = "us-east4"
bigquery_dataset_id       = "dsci_churn_prediction_new_main"
enable_feature_store      = true
featurestore_node_count   = 1

common_labels = {
  team    = "dsci"
  project = "churn_prediction_new"
  env     = "dev"
}
