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
    "aiplatform.googleapis.com",       # Vertex AI / Agent Platform
    "firestore.googleapis.com",        # Firestore (Profiles, Sessions, Training Log)
    "cloudtrace.googleapis.com",       # Cloud Trace (Telemetry)
    "logging.googleapis.com",          # Cloud Logging (Telemetry)
    "run.googleapis.com",              # Cloud Run (Web App)
    "cloudbuild.googleapis.com",       # Cloud Build (gcloud run deploy --source)
    "artifactregistry.googleapis.com", # Artifact Registry (Web App image)
    "iap.googleapis.com",              # Cloud Run IAP (Web App sign-in)
    "cloudkms.googleapis.com",         # Cloud KMS (per-runner TrainingPeaks cookie encryption)
  ]
}

resource "google_project_service" "services" {
  for_each           = toset(local.apis)
  service            = each.key
  disable_on_destroy = false
}

# 2. Dedicated Service Accounts (Agent Runtime + Cloud Run Web App)
resource "google_service_account" "agent_sa" {
  account_id   = var.agent_sa_name
  display_name = "Running Coach Agent Identity"
  description  = "Dedicated identity for the AI Running Coach agent in Vertex AI"
  depends_on   = [google_project_service.services]
}

resource "google_service_account" "web_sa" {
  account_id   = var.web_sa_name
  display_name = "Running Coach Web App Identity"
  description  = "Dedicated identity for the AI Running Coach Cloud Run web app"
  depends_on   = [google_project_service.services]
}

# 3. Grant IAM Roles to Service Accounts
locals {
  agent_roles = [
    "roles/aiplatform.user",                  # Call Gemini models
    "roles/datastore.user",                   # Read/write Firestore sessions & reports
    "roles/cloudtrace.agent",                 # Write Telemetry traces
    "roles/logging.logWriter",                # Write Telemetry logs
    "roles/serviceusage.serviceUsageConsumer" # Quota-project header on GCS (gcsfs completion uploads)
  ]
  web_roles = [
    "roles/aiplatform.user",   # Call Agent Runtime HTTP passthrough
    "roles/datastore.user",    # Read/write Firestore profiles & encrypted credentials
    "roles/logging.logWriter", # Write Cloud Run logs
    "roles/cloudtrace.agent",  # Write Cloud Trace spans
  ]
}

resource "google_project_iam_member" "agent_role_bindings" {
  for_each = toset(local.agent_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_project_iam_member" "web_role_bindings" {
  for_each = toset(local.web_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.web_sa.email}"
}

# 4. Retired Shared TrainingPeaks Cookie Secret
# Stop managing the legacy Secret Manager resources WITHOUT deleting them so the currently
# deployed agent stays functional until the new version is live. Delete the secret manually
# (`gcloud secrets delete tp-auth-cookie`) only after verifying per-runner KMS credentials.
removed {
  from = google_secret_manager_secret.tp_cookie_secret
  lifecycle {
    destroy = false
  }
}

removed {
  from = google_secret_manager_secret_iam_member.sa_secret_accessor
  lifecycle {
    destroy = false
  }
}

# 5. Cloud KMS Key for Per-Runner TrainingPeaks Cookie Encryption
# Least privilege split: Web SA can ONLY encrypt; Agent SA can ONLY decrypt.
resource "google_kms_key_ring" "coach" {
  name       = var.kms_key_ring_name
  location   = var.region
  depends_on = [google_project_service.services]
}

resource "google_kms_crypto_key" "tp_cookie" {
  name            = var.tp_cookie_kms_key_name
  key_ring        = google_kms_key_ring.coach.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = true # Destroying this key makes all stored runner cookies unreadable
  }
}

resource "google_kms_crypto_key_iam_member" "agent_decrypt" {
  crypto_key_id = google_kms_crypto_key.tp_cookie.id
  role          = "roles/cloudkms.cryptoKeyDecrypter"
  member        = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_kms_crypto_key_iam_member" "web_encrypt" {
  crypto_key_id = google_kms_crypto_key.tp_cookie.id
  role          = "roles/cloudkms.cryptoKeyEncrypter"
  member        = "serviceAccount:${google_service_account.web_sa.email}"
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

# 7b. TTL policy on the workout-analysis cache (projection cache): Firestore deletes each
#     document after its `expire_at` (workout date + 90 days, set by save_workout_analysis).
#     No index_config: Enterprise-edition databases have no built-in single-field indexes.
resource "google_firestore_field" "workout_analyses_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default_db.name
  collection = "workout_analyses"
  field      = "expire_at"

  ttl_config {}
}

# 7b-sessions. TTL on ADK session data: the agent stamps `expire_at` (last activity + 7 days)
#              on every session doc and event doc; Firestore deletes both. TTL never cascades
#              to subcollections, so `events` needs its own policy.
resource "google_firestore_field" "sessions_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default_db.name
  collection = "sessions"
  field      = "expire_at"

  ttl_config {}
}

resource "google_firestore_field" "session_events_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default_db.name
  collection = "events"
  field      = "expire_at"

  ttl_config {}
}

# 7c. Index for list_training_records(): range filter on `date` within each runner's
#     users/{id}/training_log. Enterprise edition has no built-in single-field indexes,
#     so without this the query scans the whole collection.
resource "google_firestore_index" "training_log_by_date" {
  project     = var.project_id
  database    = google_firestore_database.default_db.name
  collection  = "training_log"
  query_scope = "COLLECTION" # per-runner subcollection query (not a collection-group query)
  api_scope   = "ANY_API"    # Firestore native API (Python client)
  density     = "DENSE"      # Enterprise default; every record has `date`

  fields {
    field_path = "date"
    order      = "ASCENDING"
  }
}

# 7d. Index for find_user_profile_by_email(): equality lookup on `email` in `users`.
#     Enterprise edition has no built-in single-field indexes.
resource "google_firestore_index" "users_by_email" {
  project     = var.project_id
  database    = google_firestore_database.default_db.name
  collection  = "users"
  query_scope = "COLLECTION"
  api_scope   = "ANY_API"
  density     = "DENSE"

  fields {
    field_path = "email"
    order      = "ASCENDING"
  }
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

output "web_service_account_email" {
  value       = google_service_account.web_sa.email
  description = "The service account email for the Cloud Run web app"
}

output "tp_cookie_kms_key_id" {
  value       = google_kms_crypto_key.tp_cookie.id
  description = "Cloud KMS cryptoKey resource ID used for per-runner TrainingPeaks cookies"
}


