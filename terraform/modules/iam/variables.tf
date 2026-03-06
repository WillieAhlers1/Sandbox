variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "team" {
  description = "Team name (used in service account naming)"
  type        = string
}

variable "project_name" {
  description = "Project name (used in service account naming)"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "wif_pool_id" {
  description = "Workload Identity Federation pool ID"
  type        = string
  default     = "github-actions-pool"
}

variable "wif_provider_id" {
  description = "Workload Identity Federation provider ID"
  type        = string
  default     = "github-actions-provider"
}

variable "github_org" {
  description = "GitHub organization name for WIF"
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository name for WIF (org/repo format)"
  type        = string
  default     = ""
}
