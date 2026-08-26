import os

def get_secret_name() -> str:
    project_id = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("GCP Project ID must be set via FIRESTORE_PROJECT_ID or GOOGLE_CLOUD_PROJECT environment variable.")
    return f"projects/{project_id}/secrets/tp-auth-cookie/versions/latest"

def inject_production_secrets() -> None:
    """Injects secrets from GCP Secret Manager into environment variables at runtime in production."""
    if not os.environ.get("K_SERVICE"):
        return  # Local development; rely on local .env file
        
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = get_secret_name()
        response = client.access_secret_version(request={"name": secret_name})
        cookie_value = response.payload.data.decode("UTF-8").strip()
        
        # Inject into environment so the MCP subprocess inherits it
        os.environ["TP_AUTH_COOKIE"] = cookie_value
        print("DEBUG: Successfully injected TP_AUTH_COOKIE from Secret Manager.")
    except Exception as e:
        print(f"Error injecting production secrets: {e}")
