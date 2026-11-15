from __future__ import annotations

from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .config import firestore_database, gcp_project_id

_client: Optional[firestore.AsyncClient] = None
_known_runner_ids: set[str] = set()


def clear_known_runners_cache() -> None:
    """Clears the in-memory set of verified runner IDs (used in tests)."""
    _known_runner_ids.clear()


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


async def delete_document(collection_path: str, doc_id: str) -> None:
    """Asynchronously deletes a document from Firestore (no-op if absent)."""
    doc_ref = _get_doc_ref(collection_path, doc_id)
    await doc_ref.delete()


# ==============================================================================
# Profiles, caches and training log
# ==============================================================================

async def get_user_profile(user_id: str) -> Optional[dict[str, Any]]:
    """Asynchronously reads the user profile document from the 'users' collection."""
    doc = await read_document("users", user_id)
    if doc is not None and user_id:
        _known_runner_ids.add(user_id)
    return doc


async def user_profile_exists(user_id: str) -> bool:
    """True when `users/{user_id}` exists as a persisted runner profile (blocks eval/phantom writes)."""
    clean_id = str(user_id or "").strip()
    if not clean_id:
        return False
    if clean_id in _known_runner_ids:
        return True
    return (await get_user_profile(clean_id)) is not None


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
    runner_id, profile = matches[0]
    _known_runner_ids.add(runner_id)
    return runner_id, profile


async def save_user_profile(user_id: str, profile_data: dict[str, Any]) -> None:
    """Asynchronously persists the user profile document into the 'users' collection."""
    await write_document("users", user_id, profile_data)
    if user_id:
        _known_runner_ids.add(user_id)


async def update_user_profile(user_id: str, updates: dict[str, Any]) -> None:
    """Asynchronously updates specific fields of the user profile in the 'users' collection."""
    await update_document("users", user_id, updates)


VOLUME_HISTORY_DOC_ID = "volume_history"
RACE_PROJECTION_DOC_ID = "race_projection"


async def get_cached_volume_history(user_id: str) -> Optional[dict[str, Any]]:
    """Reads cached 12-week completed volume history from 'users/{user_id}/cache/volume_history'."""
    return await read_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID)


async def save_volume_history(user_id: str, payload: dict[str, Any]) -> None:
    """Writes 12-week completed volume history + `fetched_at` timestamp to 'users/{user_id}/cache/volume_history'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID, payload)


async def get_cached_race_projection(user_id: str) -> Optional[dict[str, Any]]:
    """Reads the cached 12-week race projection from 'users/{user_id}/cache/race_projection'."""
    return await read_document(f"users/{user_id}/cache", RACE_PROJECTION_DOC_ID)


async def save_race_projection(user_id: str, payload: dict[str, Any]) -> None:
    """Writes the cached 12-week race projection to 'users/{user_id}/cache/race_projection'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", RACE_PROJECTION_DOC_ID, payload)


async def delete_race_projection(user_id: str) -> None:
    """Deletes the cached race projection at 'users/{user_id}/cache/race_projection'."""
    await delete_document(f"users/{user_id}/cache", RACE_PROJECTION_DOC_ID)


async def save_training_record(user_id: str, workout_id: str, record: dict[str, Any]) -> None:
    """Writes (fully replaces) 'users/{user_id}/training_log/{workout_id}' for persisted runner profiles."""
    if not await user_profile_exists(user_id):
        return
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
    "clear_known_runners_cache",
    "read_document",
    "write_document",
    "update_document",
    "delete_document",
    "get_user_profile",
    "user_profile_exists",
    "find_user_profile_by_email",
    "save_user_profile",
    "update_user_profile",
    "get_cached_volume_history",
    "save_volume_history",
    "get_cached_race_projection",
    "save_race_projection",
    "delete_race_projection",
    "save_training_record",
    "list_training_records",
]

