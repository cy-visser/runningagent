"""Environment-driven settings and Cloud Run startup safety guards."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional

DEFAULT_FIRESTORE_DATABASE = "running-coach"
DEFAULT_KMS_LOCATION = "europe-west4"
DEFAULT_KMS_KEY_RING = "running-coach"
DEFAULT_KMS_KEY_NAME = "tp-cookie"
DEFAULT_AGENT_APP_NAME = "running_coach"


@dataclass(frozen=True)
class Settings:
    auth_mode: str
    iap_audience: Optional[str]
    dev_user_email: Optional[str]
    project_id: Optional[str]
    firestore_database: str
    tp_cookie_kms_key: Optional[str]
    agent_runtime_resource: Optional[str]
    agent_base_url: Optional[str]
    agent_app_name: str
    static_dir: str
    k_service: Optional[str]


def load_settings() -> Settings:
    project_id = (
        (os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
        or None
    )
    kms_key = (os.environ.get("TP_COOKIE_KMS_KEY") or "").strip() or None
    if not kms_key and project_id:
        kms_key = (
            f"projects/{project_id}/locations/{DEFAULT_KMS_LOCATION}"
            f"/keyRings/{DEFAULT_KMS_KEY_RING}/cryptoKeys/{DEFAULT_KMS_KEY_NAME}"
        )

    return Settings(
        auth_mode=(os.environ.get("AUTH_MODE") or "iap").strip().lower(),
        iap_audience=(os.environ.get("IAP_AUDIENCE") or "").strip() or None,
        dev_user_email=(os.environ.get("DEV_USER_EMAIL") or "").strip().lower() or None,
        project_id=project_id,
        firestore_database=(os.environ.get("FIRESTORE_DATABASE") or DEFAULT_FIRESTORE_DATABASE).strip(),
        tp_cookie_kms_key=kms_key,
        agent_runtime_resource=(os.environ.get("AGENT_RUNTIME_RESOURCE") or "").strip() or None,
        agent_base_url=(os.environ.get("AGENT_BASE_URL") or "").strip().rstrip("/") or None,
        agent_app_name=(os.environ.get("AGENT_APP_NAME") or DEFAULT_AGENT_APP_NAME).strip(),
        static_dir=(os.environ.get("STATIC_DIR") or "/app/static").strip(),
        k_service=(os.environ.get("K_SERVICE") or "").strip() or None,
    )


def validate_startup_settings(settings: Settings) -> None:
    """Fails closed if auth mode or IAP audience is misconfigured."""
    if settings.auth_mode not in ("iap", "dev"):
        raise RuntimeError(f"Unsupported AUTH_MODE={settings.auth_mode!r}; expected 'iap' or 'dev'.")
    if settings.auth_mode == "dev" and settings.k_service:
        raise RuntimeError(
            "Refusing to start with AUTH_MODE=dev on Cloud Run (K_SERVICE is set)."
        )
    if settings.auth_mode == "dev" and not settings.dev_user_email:
        raise RuntimeError("DEV_USER_EMAIL is required when AUTH_MODE=dev.")
    if settings.auth_mode == "iap" and settings.k_service and not settings.iap_audience:
        raise RuntimeError("IAP_AUDIENCE is required when AUTH_MODE=iap on Cloud Run.")
