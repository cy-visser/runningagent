import logging
from typing import Optional

from .config import gcp_project_id, tp_cookie_secret_id

logger = logging.getLogger(__name__)


def get_secret_name() -> str:
    """Returns the fully-qualified Secret Manager resource name for the TP cookie."""
    project_id = gcp_project_id()
    if not project_id:
        raise ValueError(
            "GCP Project ID must be set via FIRESTORE_PROJECT_ID or GOOGLE_CLOUD_PROJECT "
            "environment variable."
        )
    return f"projects/{project_id}/secrets/{tp_cookie_secret_id()}/versions/latest"


def get_tp_cookie() -> Optional[str]:
    """Reads the TrainingPeaks auth cookie from Secret Manager.

    Used by both local runs (via Application Default Credentials) and deployed Agent
    Runtime instances (via the agent service account). Never reads from or writes to
    process environment variables.
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": get_secret_name()})
        cookie = response.payload.data.decode("UTF-8").strip()
        if cookie:
            logger.info("Loaded TrainingPeaks auth cookie from Secret Manager.")
            return cookie
        logger.warning("Secret Manager returned an empty TrainingPeaks cookie.")
        return None
    except Exception as e:
        logger.error("Failed to load TrainingPeaks cookie from Secret Manager: %s", e)
        return None

