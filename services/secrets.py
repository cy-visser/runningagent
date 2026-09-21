import logging
import os

logger = logging.getLogger(__name__)

SECRET_ID = "tp-auth-cookie"


def get_secret_name() -> str:
    """Returns the fully-qualified Secret Manager resource name for the TP cookie."""
    project_id = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError(
            "GCP Project ID must be set via FIRESTORE_PROJECT_ID or GOOGLE_CLOUD_PROJECT "
            "environment variable."
        )
    return f"projects/{project_id}/secrets/{SECRET_ID}/versions/latest"


def inject_production_secrets() -> None:
    """Injects secrets from GCP Secret Manager into environment variables at runtime in production."""
    if not os.environ.get("K_SERVICE"):
        return  # Local development; rely on local .env file

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": get_secret_name()})
        # Inject into environment so the MCP subprocess inherits it.
        os.environ["TP_AUTH_COOKIE"] = response.payload.data.decode("UTF-8").strip()
        logger.info("Injected TP_AUTH_COOKIE from Secret Manager.")
    except Exception as e:
        logger.error("Failed to inject production secrets: %s", e)
