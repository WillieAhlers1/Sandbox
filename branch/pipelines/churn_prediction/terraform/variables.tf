# Terraform variables for churn_prediction pipeline

variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  default     = "us-east4"
  description = "GCP region"
}

variable "bigquery_dataset_id" {
  type        = string
  default     = "dsci_churn_prediction_main"
  description = "BigQuery dataset ID"
}

variable "enable_feature_store" {
  type        = bool
  default     = true
  description = "Enable Vertex AI Feature Store provisioning"
}

variable "featurestore_node_count" {
  type        = number
  default     = 1
  description = "Number of nodes for Feature Store online serving"
}

variable "common_labels" {
  type        = map(string)
  default     = {}
  description = "Common labels for all resources"
}

variable "shell_interpreter" {
  type        = list(string)
  default     = ["bash", "-c"]
  description = "Shell interpreter for local-exec"
}
