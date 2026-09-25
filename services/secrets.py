import logging
import os

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


def inject_production_secrets() -> None:
    """Loads TP_AUTH_COOKIE from Secret Manager when it is not already in the environment.

    Locally the cookie comes from `.env`. Deployments deliberately ship without it
    (see deploy.sh / .ae_ignore), so a missing cookie means "fetch it from Secret
    Manager" regardless of the hosting platform.
    """
    if os.environ.get("TP_AUTH_COOKIE"):
        return

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": get_secret_name()})
        # Inject into environment so the MCP subprocess inherits it.
        os.environ["TP_AUTH_COOKIE"] = response.payload.data.decode("UTF-8").strip()
        logger.info("Injected TP_AUTH_COOKIE from Secret Manager.")
    except Exception as e:
        logger.error("Failed to inject production secrets: %s", e)
