terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0"
    }
  }

  # TODO: Migrate to GCS backend after state bucket creation
  # bucket = "prj-0n-dta-pt-ai-sandbox-terraform-state", prefix = "dev"
  backend "local" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# --- Variables ---

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "team" {
  description = "Team name"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

locals {
  project_slug = replace(var.project_name, "_", "-")
}

# --- Modules ---
# NOTE: IAM and Composer modules are skipped for this enterprise project.
# Pre-existing SAs and Composer environment are used instead:
#   Pipeline SA: gc-sa-for-vertex-ai-pipelines@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com
#   Composer SA: gc-sa-for-composer-env@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com
#   Composer env: mlopshousingpoc (shared, private, VPC SC perimeter)

module "storage" {
  source      = "../../modules/storage"
  project_id  = var.project_id
  region      = var.region
  bucket_name = "${var.project_id}-${var.team}-${local.project_slug}"
  labels = {
    team        = var.team
    project     = var.project_name
    environment = var.environment
  }
}

module "artifact_registry" {
  source        = "../../modules/artifact_registry"
  project_id    = var.project_id
  region        = var.region
  repository_id = "${var.team}-${local.project_slug}"
  description   = "Docker repository for ${var.team}/${var.project_name} (${var.environment})"
  labels = {
    team        = var.team
    project     = var.project_name
    environment = var.environment
  }
}

# --- IAM for pre-existing service accounts ---
# The IAM module is not used in this environment because the SAs are
# pre-provisioned. Grant only the permissions the framework requires.

# Composer SA needs aiplatform.user to submit Vertex AI pipeline jobs
resource "google_project_iam_member" "composer_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:gc-sa-for-composer-env@${var.project_id}.iam.gserviceaccount.com"
}

# Allow Composer SA to act as the Pipeline SA when submitting Vertex jobs
resource "google_service_account_iam_member" "composer_acts_as_pipeline" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/gc-sa-for-vertex-ai-pipelines@${var.project_id}.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:gc-sa-for-composer-env@${var.project_id}.iam.gserviceaccount.com"
}

# --- Outputs ---

output "artifact_registry_url" {
  description = "Docker registry URL"
  value       = module.artifact_registry.repository_url
}

output "bucket_name" {
  description = "GCS bucket name"
  value       = module.storage.bucket_name
}
