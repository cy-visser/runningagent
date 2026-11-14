from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .config import firestore_database, gcp_project_id

_client: Optional[firestore.AsyncClient] = None


def make_async_client(project: Optional[str] = None) -> firestore.AsyncClient:
    """Builds a Firestore AsyncClient for the configured project and database."""
    return firestore.AsyncClient(project=project or gcp_project_id(), database=firestore_database())


def _get_client() -> firestore.AsyncClient:
    """Returns or initializes the internal Firestore async client singleton."""
    global _client
    if _client is None:
        _client = make_async_client()
    return _client


def _get_doc_ref(collection_path: str, doc_id: str):
    """Helper to resolve a DocumentReference for arbitrary collection paths or nested subcollections."""
    client = _get_client()
    clean_path = collection_path.strip("/")
    return client.document(f"{clean_path}/{doc_id}")


# ==============================================================================
# Generic operations
# ==============================================================================

async def read_document(collection_path: str, doc_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads a single document from Firestore. Returns None if the document does not exist."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    snapshot = await doc_ref.get()
    if snapshot.exists:
        return snapshot.to_dict()
    return None


async def write_document(collection_path: str, doc_id: str, data: dict[str, Any]) -> None:
    """Asynchronously writes (replaces) a document in Firestore."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    await doc_ref.set(data)


async def update_document(collection_path: str, doc_id: str, data: dict[str, Any]) -> None:
    """Asynchronously updates fields on an existing document in Firestore."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    await doc_ref.update(data)


# ==============================================================================
# Profiles, projection cache and training log
# ==============================================================================

# Projection cache entries expire this long after the workout date (Firestore TTL on `expire_at`).
CACHE_TTL_DAYS = 90


async def get_user_profile(user_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads the user profile document from the 'users' collection."""
    return await read_document("users", user_id)


async def find_user_profile_by_email(email: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Looks up `(runner_id, profile)` in `users` by normalized email (`limit(2)`).

    Raises `RuntimeError` if more than one profile carries the same email so an ambiguous
    mapping can never silently pick the wrong runner.
    """
    clean_email = str(email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return None
    query = (
        _get_client()
        .collection("users")
        .where(filter=FieldFilter("email", "==", clean_email))
        .limit(2)
    )
    matches = [(snap.id, snap.to_dict() or {}) async for snap in query.stream()]
    if not matches:
        return None
    if len(matches) > 1:
        ids = ", ".join(doc_id for doc_id, _ in matches)
        raise RuntimeError(f"Multiple runner profiles match email {clean_email!r}: {ids}")
    return matches[0]


async def save_user_profile(user_id: str, profile_data: dict[str, Any]) -> None:
    """Asynchronously persists the user profile document into the 'users' collection."""
    await write_document("users", user_id, profile_data)


async def update_user_profile(user_id: str, updates: dict[str, Any]) -> None:
    """Asynchronously updates specific fields of the user profile in the 'users' collection."""
    await update_document("users", user_id, updates)


async def get_cached_workout_analysis(user_id: str, workout_id: str) -> Optional[dict[str, Any]]:
    """Reads a cached workout-analysis summary from 'users/{user_id}/workout_analyses/{workout_id}'."""
    return await read_document(f"users/{user_id}/workout_analyses", str(workout_id))


def cache_expiry(workout_date: Optional[str]) -> datetime:
    """TTL timestamp for a cache entry: workout date (or now) + CACHE_TTL_DAYS, timezone-aware."""
    try:
        start = datetime.fromisoformat(str(workout_date)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        start = datetime.now(timezone.utc)
    return start + timedelta(days=CACHE_TTL_DAYS)


async def save_workout_analysis(user_id: str, workout_id: str, summary: dict[str, Any]) -> None:
    """Persists a workout-analysis summary to 'users/{user_id}/workout_analyses/{workout_id}' with its TTL."""
    data = {**summary, "expire_at": cache_expiry(summary.get("date"))}
    await write_document(f"users/{user_id}/workout_analyses", str(workout_id), data)


VOLUME_HISTORY_DOC_ID = "volume_history"


async def get_cached_volume_history(user_id: str) -> Optional[dict[str, Any]]:
    """Reads cached 12-week completed volume history from 'users/{user_id}/cache/volume_history'."""
    return await read_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID)


async def save_volume_history(user_id: str, payload: dict[str, Any]) -> None:
    """Writes 12-week completed volume history + `fetched_at` timestamp to 'users/{user_id}/cache/volume_history'."""
    await write_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID, payload)


async def save_training_record(user_id: str, workout_id: str, record: dict[str, Any]) -> None:
    """Writes (fully replaces) 'users/{user_id}/training_log/{workout_id}'."""
    await write_document(f"users/{user_id}/training_log", str(workout_id), record)


async def list_training_records(user_id: str, start: str, end: str) -> list[dict[str, Any]]:
    """Training-log records with start <= date <= end (ISO dates), oldest first."""
    query = (
        _get_client().collection(f"users/{user_id}/training_log")
        .where(filter=FieldFilter("date", ">=", start))
        .where(filter=FieldFilter("date", "<=", end))
    )
    records = [snap.to_dict() async for snap in query.stream()]
    return sorted(records, key=lambda r: (r.get("date") or "", r.get("workout_id") or ""))


__all__ = [
    "make_async_client",
    "read_document",
    "write_document",
    "update_document",
    "get_user_profile",
    "find_user_profile_by_email",
    "save_user_profile",
    "update_user_profile",
    "get_cached_workout_analysis",
    "save_workout_analysis",
    "get_cached_volume_history",
    "save_volume_history",
    "save_training_record",
    "list_training_records",
]

