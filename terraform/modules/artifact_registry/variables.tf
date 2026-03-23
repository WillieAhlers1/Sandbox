variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "repository_id" {
  description = "Artifact Registry repository ID"
  type        = string
}

variable "description" {
  description = "Repository description"
  type        = string
  default     = "Docker repository for ML pipeline containers"
}

variable "labels" {
  description = "Labels to apply to the repository"
  type        = map(string)
  default     = {}
}
