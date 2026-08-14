import os
from typing import Optional
from google.cloud import firestore

PROJECT_ID = os.environ.get("FIRESTORE_PROJECT_ID")
DATABASE_NAME = os.environ.get("FIRESTORE_DATABASE", "running-coach")

# Synchronous Firestore client singleton
db_client = firestore.Client(project=PROJECT_ID, database=DATABASE_NAME)

def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"
