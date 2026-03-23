variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "environment_name" {
  description = "Cloud Composer environment name"
  type        = string
}

variable "image_version" {
  description = "Composer image version (e.g. composer-3-airflow-2.10.5-build.27)"
  type        = string
  default     = "composer-3-airflow-2"
}

variable "environment_size" {
  description = "Predefined environment size (ENVIRONMENT_SIZE_SMALL, ENVIRONMENT_SIZE_MEDIUM, ENVIRONMENT_SIZE_LARGE)"
  type        = string
  default     = "ENVIRONMENT_SIZE_SMALL"
}

variable "service_account_email" {
  description = "Service account email for the Composer environment"
  type        = string
}

variable "network" {
  description = "VPC network self-link"
  type        = string
  default     = ""
}

variable "subnetwork" {
  description = "VPC subnetwork self-link"
  type        = string
  default     = ""
}

variable "scheduler" {
  description = "Scheduler workload config"
  type = object({
    cpu        = number
    memory_gb  = number
    storage_gb = number
    count      = number
  })
  default = {
    cpu        = 0.5
    memory_gb  = 2
    storage_gb = 1
    count      = 1
  }
}

variable "triggerer" {
  description = "Triggerer workload config"
  type = object({
    cpu       = number
    memory_gb = number
    count     = number
  })
  default = {
    cpu       = 0.5
    memory_gb = 1
    count     = 1
  }
}

variable "dag_processor" {
  description = "DAG processor workload config"
  type = object({
    cpu        = number
    memory_gb  = number
    storage_gb = number
    count      = number
  })
  default = {
    cpu        = 1
    memory_gb  = 2
    storage_gb = 1
    count      = 1
  }
}

variable "web_server" {
  description = "Web server workload config"
  type = object({
    cpu        = number
    memory_gb  = number
    storage_gb = number
  })
  default = {
    cpu        = 0.5
    memory_gb  = 2
    storage_gb = 1
  }
}

variable "worker" {
  description = "Worker workload config"
  type = object({
    cpu        = number
    memory_gb  = number
    storage_gb = number
    min_count  = number
    max_count  = number
  })
  default = {
    cpu        = 0.5
    memory_gb  = 2
    storage_gb = 1
    min_count  = 1
    max_count  = 3
  }
}

variable "pypi_packages" {
  description = "PyPI packages to install in the Composer environment"
  type        = map(string)
  default     = {}
}

variable "env_variables" {
  description = "Environment variables for Airflow"
  type        = map(string)
  default     = {}
}

variable "labels" {
  description = "Labels to apply to the Composer environment"
  type        = map(string)
  default     = {}
}
