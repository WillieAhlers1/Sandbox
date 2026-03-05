output "composer_service_account_email" {
  description = "Composer service account email"
  value       = google_service_account.composer.email
}

output "pipeline_service_account_email" {
  description = "Pipeline service account email"
  value       = google_service_account.pipeline.email
}

output "wif_pool_name" {
  description = "Workload Identity Federation pool name"
  value       = var.github_repo != "" ? google_iam_workload_identity_pool.github[0].name : ""
}

output "wif_provider_name" {
  description = "Workload Identity Federation provider name"
  value       = var.github_repo != "" ? google_iam_workload_identity_pool_provider.github[0].name : ""
}
