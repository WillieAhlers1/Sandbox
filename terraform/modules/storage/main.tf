terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }
}

resource "google_storage_bucket" "this" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = var.storage_class
  uniform_bucket_level_access = true
  labels                      = var.labels

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.lifecycle_age_days > 0 ? [1] : []
    content {
      action {
        type = "Delete"
      }
      condition {
        age = var.lifecycle_age_days
      }
    }
  }
}
