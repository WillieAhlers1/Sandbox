# Main Terraform configuration for churn_prediction pipeline provisioning
# Includes: BigQuery dataset, SQL execution, Docker image build, Artifact Registry

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ─────────────────────────────────────────────────────────────────────────────
# Local Variables for Dynamic File Discovery
# ─────────────────────────────────────────────────────────────────────────────

locals {
  bq_sql_files = try(fileset("${path.module}/../sql/BQ", "*.sql"), [])
  fs_sql_files = try(fileset("${path.module}/../sql/FS", "*.sql"), [])
}

# ─────────────────────────────────────────────────────────────────────────────
# BigQuery Dataset
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "churn_prediction_dataset" {
  dataset_id           = var.bigquery_dataset_id
  friendly_name        = "churn_prediction Dataset"
  description          = "Dataset for churn_prediction pipeline"
  location             = var.region
  default_table_expiration_ms = null
  default_partition_expiration_ms = null
  
  labels = merge(
    var.common_labels,
    {
      pipeline = "churn_prediction"
      managed_by = "terraform"
    }
  )
}

# ─────────────────────────────────────────────────────────────────────────────
# BigQuery: Execute SQL Files from BQ folder
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_job" "execute_bq_sql" {
  for_each = local.bq_sql_files
  
  job_id           = "${var.bigquery_dataset_id}-${replace(each.key, ".sql", "")}-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"
  location         = var.region
  labels           = merge(var.common_labels, { pipeline = "churn_prediction", managed_by = "terraform" })

  query {
    query          = templatefile("${path.module}/../sql/BQ/${each.key}", {
      bq_dataset = var.bigquery_dataset_id
      run_date   = formatdate("YYYY-MM-DD", timestamp())
    })
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_dataset.churn_prediction_dataset]
}

# ─────────────────────────────────────────────────────────────────────────────
# Feature Store: Execute SQL Files from FS folder
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_job" "execute_fs_sql" {
  for_each = local.fs_sql_files
  
  job_id           = "${var.bigquery_dataset_id}-fs-${replace(each.key, ".sql", "")}-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"
  location         = var.region
  labels           = merge(var.common_labels, { pipeline = "churn_prediction", managed_by = "terraform" })

  query {
    query          = templatefile("${path.module}/../sql/FS/${each.key}", {
      bq_dataset = var.bigquery_dataset_id
      run_date   = formatdate("YYYY-MM-DD", timestamp())
    })
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_dataset.churn_prediction_dataset]
}

# ─────────────────────────────────────────────────────────────────────────────
# Artifact Registry for Docker Images
# ─────────────────────────────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "churn_prediction_repo" {
  location      = var.region
  repository_id = replace("churn_prediction", "_", "-")
  description   = "Docker images for churn_prediction pipeline"
  format        = "DOCKER"

  labels = merge(
    var.common_labels,
    {
      pipeline = "churn_prediction"
      managed_by = "terraform"
    }
  )
}

# ─────────────────────────────────────────────────────────────────────────────
# Docker Image Build (Local Execution)
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_build" {
  provisioner "local-exec" {
    command     = "docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${replace("churn_prediction", "_", "-")}/trainer:latest -f trainer/Dockerfile ."
    working_dir = "${path.module}/.."
    interpreter = var.shell_interpreter
  }

  triggers = {
    dockerfile_hash = filemd5("${path.module}/../trainer/Dockerfile")
  }

  depends_on = [google_artifact_registry_repository.churn_prediction_repo]
}

# ─────────────────────────────────────────────────────────────────────────────
# Configure Docker Auth with Artifact Registry
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_auth" {
  provisioner "local-exec" {
    command     = "gcloud auth configure-docker ${var.region}-docker.pkg.dev"
    interpreter = var.shell_interpreter
  }

  depends_on = [google_artifact_registry_repository.churn_prediction_repo]
}

# ─────────────────────────────────────────────────────────────────────────────
# Docker Image Push
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_push" {
  provisioner "local-exec" {
    command     = "docker push ${var.region}-docker.pkg.dev/${var.project_id}/${replace("churn_prediction", "_", "-")}/trainer:latest"
    working_dir = "${path.module}/.."
    interpreter = var.shell_interpreter
  }

  depends_on = [
    null_resource.docker_build,
    null_resource.docker_auth
  ]
}
