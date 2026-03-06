terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }
}

resource "google_composer_environment" "this" {
  provider = google-beta
  project  = var.project_id
  name     = var.environment_name
  region   = var.region
  labels   = var.labels

  config {
    environment_size = var.environment_size

    software_config {
      image_version = var.image_version
      pypi_packages = var.pypi_packages
      env_variables = var.env_variables
    }

    node_config {
      service_account = var.service_account_email
    }

    workloads_config {
      scheduler {
        cpu        = var.scheduler.cpu
        memory_gb  = var.scheduler.memory_gb
        storage_gb = var.scheduler.storage_gb
        count      = var.scheduler.count
      }

      triggerer {
        cpu       = var.triggerer.cpu
        memory_gb = var.triggerer.memory_gb
        count     = var.triggerer.count
      }

      dag_processor {
        cpu        = var.dag_processor.cpu
        memory_gb  = var.dag_processor.memory_gb
        storage_gb = var.dag_processor.storage_gb
        count      = var.dag_processor.count
      }

      web_server {
        cpu        = var.web_server.cpu
        memory_gb  = var.web_server.memory_gb
        storage_gb = var.web_server.storage_gb
      }

      worker {
        cpu        = var.worker.cpu
        memory_gb  = var.worker.memory_gb
        storage_gb = var.worker.storage_gb
        min_count  = var.worker.min_count
        max_count  = var.worker.max_count
      }
    }
  }
}
