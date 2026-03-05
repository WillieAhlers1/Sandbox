output "repository_id" {
  description = "The repository ID"
  value       = google_artifact_registry_repository.this.repository_id
}

output "repository_name" {
  description = "The full resource name of the repository"
  value       = google_artifact_registry_repository.this.name
}

output "repository_url" {
  description = "The Docker registry URL (region-docker.pkg.dev/project/repo)"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.this.repository_id}"
}
