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
  bucket_name = "${var.project_id}-${var.team}-${var.project_name}"
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
  repository_id = "${var.team}-${var.project_name}"
  description   = "Docker repository for ${var.team}/${var.project_name} (${var.environment})"
  labels = {
    team        = var.team
    project     = var.project_name
    environment = var.environment
  }
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
