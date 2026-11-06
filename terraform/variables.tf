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

variable "web_sa_name" {
  type        = string
  default     = "running-coach-web"
  description = "The account ID for the dedicated Cloud Run Web App Service Account"
}

variable "firestore_db_name" {
  type        = string
  default     = "running-coach"
  description = "The Firestore database name for the running agent"
}

variable "kms_key_ring_name" {
  type        = string
  default     = "running-coach"
  description = "Cloud KMS key ring name for encrypting per-runner credentials"
}

variable "tp_cookie_kms_key_name" {
  type        = string
  default     = "tp-cookie"
  description = "Cloud KMS cryptoKey name used for per-runner TrainingPeaks cookies"
}

variable "traces_bucket_name" {
  description = "Cloud Storage bucket for GenAI prompt/response completion logs"
  type        = string
  default     = "traces_runningagent"
}


