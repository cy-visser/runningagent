terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.45.2"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Enable Required APIs
locals {
  apis = [
    "aiplatform.googleapis.com",      # Vertex AI / Agent Platform
    "discoveryengine.googleapis.com", # Gemini Enterprise (Discovery Engine)
    "secretmanager.googleapis.com",   # Secret Manager
    "firestore.googleapis.com",       # Firestore (Session State)
    "cloudtrace.googleapis.com",      # Cloud Trace (Telemetry)
    "logging.googleapis.com"          # Cloud Logging (Telemetry)
  ]
}

resource "google_project_service" "services" {
  for_each           = toset(local.apis)
  service            = each.key
  disable_on_destroy = false
}

# 2. Create the Dedicated Service Account
resource "google_service_account" "agent_sa" {
  account_id   = var.agent_sa_name
  display_name = "Running Coach Agent Identity"
  description  = "Dedicated identity for the AI Running Coach agent in Vertex AI"
  depends_on   = [google_project_service.services]
}

# 3. Grant IAM Roles to the Service Account
locals {
  agent_roles = [
    "roles/aiplatform.user",     # Call Gemini models
    "roles/datastore.user",      # Read/write Firestore sessions & reports
    "roles/cloudtrace.agent",    # Write Telemetry traces
    "roles/logging.logWriter"    # Write Telemetry logs
  ]
}

resource "google_project_iam_member" "agent_role_bindings" {
  for_each = toset(local.agent_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}

# 4. Create the Secret Manager Container (Value managed by deploy script)
resource "google_secret_manager_secret" "tp_cookie_secret" {
  secret_id = var.tp_cookie_secret_id
  labels = {
    agent = "running-coach"
  }
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

# 5. Grant the Service Account Access to the Secret
resource "google_secret_manager_secret_iam_member" "sa_secret_accessor" {
  secret_id = google_secret_manager_secret.tp_cookie_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent_sa.email}"
}

# 6. Grant Service Account User to Vertex AI Service Agent (CRITICAL)
data "google_project" "project" {}

resource "google_service_account_iam_member" "vertex_sa_user" {
  service_account_id = google_service_account.agent_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "vertex_re_sa_user" {
  service_account_id = google_service_account.agent_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

# 7. Provision Firestore Database Instance (if not exists)
resource "google_firestore_database" "default_db" {
  project                           = var.project_id
  name                              = var.firestore_db_name
  location_id                       = var.region
  type                              = "FIRESTORE_NATIVE"
  database_edition                  = "ENTERPRISE"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  
  # Ensure the firestore API is fully enabled before database creation
  depends_on = [google_project_service.services]
}

# 8. Cloud Storage Bucket for Prompt & Response Telemetry (traces_runningagent)
import {
  to = google_storage_bucket.traces
  id = var.traces_bucket_name
}

resource "google_storage_bucket" "traces" {
  name                        = var.traces_bucket_name
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle {
    ignore_changes = [encryption]
  }
}

resource "google_storage_bucket_iam_member" "agent_traces_access" {
  bucket = google_storage_bucket.traces.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.agent_sa.email}"
}

output "agent_service_account_email" {
  value       = google_service_account.agent_sa.email
  description = "The service account email to configure in the agent deployment"
}

