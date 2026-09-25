"""Environment-driven configuration shared by the Firestore, session and secret services."""

import os
from typing import Optional

DEFAULT_FIRESTORE_DATABASE = "running-coach"
DEFAULT_TP_COOKIE_SECRET_ID = "tp-auth-cookie"


def gcp_project_id() -> Optional[str]:
    """GCP project hosting Firestore and Secret Manager."""
    return os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")


def firestore_database() -> str:
    """Firestore database name used for profiles, reports and sessions."""
    return os.environ.get("FIRESTORE_DATABASE", DEFAULT_FIRESTORE_DATABASE)


def tp_cookie_secret_id() -> str:
    """Secret Manager secret id holding the TrainingPeaks auth cookie."""
    return os.environ.get("TP_COOKIE_SECRET_ID", DEFAULT_TP_COOKIE_SECRET_ID)
