# Terraform outputs for churn_prediction_new pipeline

output "bigquery_dataset_id" {
  value       = google_bigquery_dataset.churn_prediction_new_dataset.dataset_id
  description = "BigQuery dataset ID"
}

output "executed_bq_sql_jobs" {
  value       = [for file, job in google_bigquery_job.execute_bq_sql : {
    sql_file = file
    job_id   = job.job_id
    status   = "executed"
  }]
  description = "BigQuery SQL jobs executed from sql/BQ/ folder"
}

output "executed_fs_sql_jobs" {
  value       = [for file, job in google_bigquery_job.execute_fs_sql : {
    sql_file = file
    job_id   = job.job_id
    status   = "executed"
  }]
  description = "Feature Store SQL jobs executed from sql/FS/ folder"
}

output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.churn_prediction_new_repo.repository_id
  description = "Artifact Registry repository ID"
}

output "artifact_registry_host" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.churn_prediction_new_repo.repository_id}"
  description = "Artifact Registry host URL for Docker images"
}

output "docker_image_uri" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.churn_prediction_new_repo.repository_id}/trainer:latest"
  description = "Full Docker image URI for trainer"
}

output "terraform_state_summary" {
  value = {
    dataset_id              = google_bigquery_dataset.churn_prediction_new_dataset.dataset_id
    artifact_registry_repo  = google_artifact_registry_repository.churn_prediction_new_repo.repository_id
    bq_sql_files_executed   = length(google_bigquery_job.execute_bq_sql)
    fs_sql_files_executed   = length(google_bigquery_job.execute_fs_sql)
    docker_image_built      = "true (via terraform apply)"
  }
  description = "Summary of all provisioned resources"
}
