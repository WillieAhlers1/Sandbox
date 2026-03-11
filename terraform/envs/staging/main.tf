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
  # bucket = "<YOUR_PROJECT_ID>-terraform-state", prefix = "staging"
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
  default     = "staging"
}

variable "github_repo" {
  description = "GitHub repository (org/repo) for WIF"
  type        = string
  default     = ""
}

# --- Modules ---

module "iam" {
  source       = "../../modules/iam"
  project_id   = var.project_id
  team         = var.team
  project_name = var.project_name
  environment  = var.environment
  github_repo  = var.github_repo
}

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

module "composer" {
  source                = "../../modules/composer"
  project_id            = var.project_id
  region                = var.region
  environment_name      = "${var.team}-${var.project_name}-${var.environment}"
  service_account_email = module.iam.composer_service_account_email
  environment_size      = "ENVIRONMENT_SIZE_SMALL"

  worker = {
    cpu        = 1
    memory_gb  = 4
    storage_gb = 2
    min_count  = 1
    max_count  = 4
  }

  labels = {
    team        = var.team
    project     = var.project_name
    environment = var.environment
  }
}

# --- Outputs ---

output "composer_dags_path" {
  description = "GCS path for Composer DAGs"
  value       = module.composer.composer_dags_path
}

output "artifact_registry_url" {
  description = "Docker registry URL"
  value       = module.artifact_registry.repository_url
}

output "bucket_name" {
  description = "GCS bucket name"
  value       = module.storage.bucket_name
}

output "composer_service_account" {
  description = "Composer service account email"
  value       = module.iam.composer_service_account_email
}

output "pipeline_service_account" {
  description = "Pipeline service account email"
  value       = module.iam.pipeline_service_account_email
}
