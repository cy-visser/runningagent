variable "project_id" {
  type        = string
  description = "The GCP Project ID (supplied via TF_VAR_project_id from .env or -var flag)"
}

variable "region" {
  type        = string
  default     = "europe-west4"
  description = "The GCP Region"
}

variable "agent_sa_name" {
  type        = string
  default     = "running-coach-agent"
  description = "The account ID for the dedicated Agent Service Account"
}

variable "firestore_db_name" {
  type        = string
  default     = "running-coach"
  description = "The Firestore database name for the running agent"
}
