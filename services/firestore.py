from __future__ import annotations
import os
from typing import Any, Optional
from google.cloud import firestore

_client: Optional[firestore.AsyncClient] = None


def _get_client() -> firestore.AsyncClient:
    """Returns or initializes the internal Firestore async client singleton."""
    global _client
    if _client is None:
        project_id = os.environ.get("FIRESTORE_PROJECT_ID")
        database_name = os.environ.get("FIRESTORE_DATABASE", "running-coach")
        _client = firestore.AsyncClient(project=project_id, database=database_name)
    return _client


def _get_doc_ref(collection_path: str, doc_id: str):
    """Helper to resolve a DocumentReference for arbitrary collection paths or nested subcollections."""
    client = _get_client()
    clean_path = collection_path.strip("/")
    return client.document(f"{clean_path}/{doc_id}")


# ==============================================================================
# Generic Async Read / Write / Update Operations
# ==============================================================================

async def read_document(collection_path: str, doc_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads a single document from Firestore. Returns None if the document does not exist."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    snapshot = await doc_ref.get()
    if snapshot.exists:
        return snapshot.to_dict()
    return None


async def write_document(collection_path: str, doc_id: str, data: dict[str, Any], merge: bool = False) -> None:
    """Asynchronously writes a document to Firestore using set (with optional merge)."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    await doc_ref.set(data, merge=merge)


async def update_document(collection_path: str, doc_id: str, data: dict[str, Any]) -> None:
    """Asynchronously updates fields on an existing document in Firestore."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    await doc_ref.update(data)


# ==============================================================================
# Domain-Specific Helper Functions (User Profile & Check-in Reports)
# ==============================================================================

def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"


async def get_user_profile(user_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads the user profile document from the 'users' collection."""
    return await read_document("users", user_id)


async def save_user_profile(user_id: str, profile_data: dict[str, Any], merge: bool = False) -> None:
    """Asynchronously persists the user profile document into the 'users' collection."""
    await write_document("users", user_id, profile_data, merge=merge)


async def update_user_profile(user_id: str, updates: dict[str, Any]) -> None:
    """Asynchronously updates specific fields of the user profile in the 'users' collection."""
    await update_document("users", user_id, updates)


async def save_checkin_report(user_id: str, doc_id: str, report_data: dict[str, Any]) -> None:
    """Asynchronously persists a weekly check-in report to 'users/{user_id}/checkins/{doc_id}'."""
    await write_document(f"users/{user_id}/checkins", doc_id, report_data)


async def get_checkin_report(user_id: str, doc_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads a weekly check-in report from 'users/{user_id}/checkins/{doc_id}'."""
    return await read_document(f"users/{user_id}/checkins", doc_id)


__all__ = [
    "get_user_id",
    "read_document",
    "write_document",
    "update_document",
    "get_user_profile",
    "save_user_profile",
    "update_user_profile",
    "save_checkin_report",
    "get_checkin_report",
]
