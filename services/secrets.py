import os

SECRET_NAME = "projects/firestore-cyvisser/secrets/tp-auth-cookie/versions/latest"

def inject_production_secrets() -> None:
    """Injects secrets from GCP Secret Manager into environment variables at runtime in production."""
    if not os.environ.get("K_SERVICE"):
        return  # Local development; rely on local .env file
        
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": SECRET_NAME})
        cookie_value = response.payload.data.decode("UTF-8").strip()
        
        # Inject into environment so the MCP subprocess inherits it
        os.environ["TP_AUTH_COOKIE"] = cookie_value
        print("DEBUG: Successfully injected TP_AUTH_COOKIE from Secret Manager.")
    except Exception as e:
        print(f"Error injecting production secrets: {e}")
