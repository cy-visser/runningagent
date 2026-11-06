"""Environment-driven configuration shared by the Firestore, session, and KMS credential services."""

import os
from typing import Optional

DEFAULT_FIRESTORE_DATABASE = "running-coach"
DEFAULT_KMS_LOCATION = "europe-west4"
DEFAULT_KMS_KEY_RING = "running-coach"
DEFAULT_TP_COOKIE_KMS_KEY = "tp-cookie"


def gcp_project_id() -> Optional[str]:
    """GCP project hosting Firestore and Cloud KMS."""
    return os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")


def firestore_database() -> str:
    """Firestore database name used for profiles, reports, credentials, and sessions."""
    return os.environ.get("FIRESTORE_DATABASE", DEFAULT_FIRESTORE_DATABASE)


def tp_cookie_kms_key() -> Optional[str]:
    """Cloud KMS cryptoKey resource name used to decrypt per-runner TrainingPeaks cookies."""
    explicit = (os.environ.get("TP_COOKIE_KMS_KEY") or "").strip()
    if explicit:
        return explicit
    project = gcp_project_id()
    if not project:
        return None
    return (
        f"projects/{project}/locations/{DEFAULT_KMS_LOCATION}"
        f"/keyRings/{DEFAULT_KMS_KEY_RING}/cryptoKeys/{DEFAULT_TP_COOKIE_KMS_KEY}"
    )


def web_app_url() -> Optional[str]:
    """Public URL of the Cloud Run web app, shown when a runner needs to link TrainingPeaks."""
    return (os.environ.get("WEB_APP_URL") or "").strip() or None


def dev_runner_email() -> Optional[str]:
    """Local-only fallback runner email for `adk web` and `adk eval` (never set in production)."""
    value = (os.environ.get("DEV_RUNNER_EMAIL") or "").strip().lower()
    return value if value and "@" in value else None
