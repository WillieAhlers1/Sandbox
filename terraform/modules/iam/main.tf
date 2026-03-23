terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }
}

locals {
  sa_name_prefix = "${var.team}-${replace(var.project_name, "_", "-")}-${var.environment}"
}

# --- Service Accounts ---

# Composer service account (runs Airflow DAGs)
resource "google_service_account" "composer" {
  project      = var.project_id
  account_id   = "${local.sa_name_prefix}-composer"
  display_name = "Composer SA for ${local.sa_name_prefix}"
}

# Pipeline service account (runs Vertex AI pipelines, BQ jobs, GCS access)
resource "google_service_account" "pipeline" {
  project      = var.project_id
  account_id   = "${local.sa_name_prefix}-pipeline"
  display_name = "Pipeline SA for ${local.sa_name_prefix}"
}

# --- IAM Bindings for Composer SA ---

resource "google_project_iam_member" "composer_worker" {
  project = var.project_id
  role    = "roles/composer.worker"
  member  = "serviceAccount:${google_service_account.composer.email}"
}

resource "google_project_iam_member" "composer_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.composer.email}"
}

resource "google_project_iam_member" "composer_bq_user" {
  project = var.project_id
  role    = "roles/bigquery.user"
  member  = "serviceAccount:${google_service_account.composer.email}"
}

resource "google_project_iam_member" "composer_gcs" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.composer.email}"
}

# --- IAM Bindings for Pipeline SA ---

resource "google_project_iam_member" "pipeline_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bq_user" {
  project = var.project_id
  role    = "roles/bigquery.user"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_gcs" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

# Composer SA needs aiplatform.user to create Vertex AI pipeline jobs
# (the API call itself runs as Composer SA; the pipeline job runs as Pipeline SA)
resource "google_project_iam_member" "composer_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.composer.email}"
}

# Allow Composer SA to act as the Pipeline SA (for submitting Vertex jobs)
resource "google_service_account_iam_member" "composer_acts_as_pipeline" {
  service_account_id = google_service_account.pipeline.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.composer.email}"
}

# --- Workload Identity Federation (for CI/CD) ---

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repo != "" ? 1 : 0
  project                   = var.project_id
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repo != "" ? 1 : 0
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub Actions Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_condition = "assertion.repository == '${var.github_repo}'"
}

# Allow GitHub Actions to impersonate the Pipeline SA via WIF
resource "google_service_account_iam_member" "wif_pipeline" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.pipeline.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}
