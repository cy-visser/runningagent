variable "project_id" {
  type        = string
  default     = "firestore-cyvisser"
  description = "The GCP Project ID"
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
