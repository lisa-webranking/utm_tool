variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west8" # Milan
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "utm-tool"
}

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro" # Smallest tier, good for small teams
}

variable "min_instances" {
  description = "Minimum Cloud Run instances (1 = no cold start)"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 3
}

variable "custom_domain" {
  description = "Optional custom domain (e.g. utm.webranking.it). Leave empty to use default Cloud Run URL."
  type        = string
  default     = ""
}
