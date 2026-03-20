output "composer_environment_id" {
  description = "The ID of the Cloud Composer environment"
  value       = google_composer_environment.this.id
}

output "composer_environment_name" {
  description = "The name of the Cloud Composer environment"
  value       = google_composer_environment.this.name
}

output "composer_dags_path" {
  description = "The GCS path for DAG files (gs://bucket/dags)"
  value       = google_composer_environment.this.config[0].dag_gcs_prefix
}

output "airflow_uri" {
  description = "The Airflow web UI URI"
  value       = google_composer_environment.this.config[0].airflow_uri
}
