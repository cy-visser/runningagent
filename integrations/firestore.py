from __future__ import annotations

from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .config import firestore_database, gcp_project_id

_client: Optional[firestore.AsyncClient] = None
_known_runner_ids: set[str] = set()
_email_runner_ids: dict[str, str] = {}


def clear_known_runners_cache() -> None:
    """Clears the in-memory set of verified runner IDs and email mappings (used in tests)."""
    _known_runner_ids.clear()
    _email_runner_ids.clear()


def cached_runner_id_for_email(email: Optional[str]) -> Optional[str]:
    """Returns the cached `runner_id` for a normalized email, if previously resolved."""
    clean = str(email or "").strip().lower()
    return _email_runner_ids.get(clean) if clean else None


def remember_email_runner_id(email: Optional[str], runner_id: Optional[str]) -> None:
    """Caches an immutable `email -> runner_id` mapping in memory."""
    clean_email = str(email or "").strip().lower()
    clean_id = str(runner_id or "").strip()
    if clean_email and "@" in clean_email and clean_id:
        _email_runner_ids[clean_email] = clean_id


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
        remember_email_runner_id(doc.get("email"), user_id)
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

    Uses an in-memory `email -> runner_id` point-read fast path when already known, verifying the
    stored document's `email` before falling back to the indexed collection query. Raises `RuntimeError`
    if more than one profile carries the same email.
    """
    clean_email = str(email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return None
    cached_id = _email_runner_ids.get(clean_email)
    if cached_id:
        doc = await get_user_profile(cached_id)
        if doc is not None and str(doc.get("email") or "").strip().lower() == clean_email:
            return cached_id, doc
        _email_runner_ids.pop(clean_email, None)

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
    remember_email_runner_id(clean_email, runner_id)
    return runner_id, profile


async def save_user_profile(user_id: str, profile_data: dict[str, Any]) -> None:
    """Asynchronously persists the user profile document into the 'users' collection."""
    await write_document("users", user_id, profile_data)
    if user_id:
        _known_runner_ids.add(user_id)
        remember_email_runner_id(profile_data.get("email"), user_id)


async def update_user_profile(user_id: str, updates: dict[str, Any]) -> None:
    """Asynchronously updates specific fields of the user profile in the 'users' collection."""
    await update_document("users", user_id, updates)


VOLUME_HISTORY_DOC_ID = "volume_history"
RACE_PROJECTION_DOC_ID = "race_projection"
YEAR_REVIEW_DOC_PREFIX = "year_review"
YEAR_REVIEW_RAW_DOC_PREFIX = "year_review_raw"
YEAR_REVIEW_INDEX_DOC_ID = "year_review_index"


def year_review_doc_id(year: int) -> str:
    return f"{YEAR_REVIEW_DOC_PREFIX}_{int(year)}"


def year_review_raw_doc_id(year: int) -> str:
    return f"{YEAR_REVIEW_RAW_DOC_PREFIX}_{int(year)}"


async def get_cached_volume_history(user_id: str) -> Optional[dict[str, Any]]:
    """Reads cached 12-week completed volume history from 'users/{user_id}/cache/volume_history'."""
    return await read_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID)


async def save_volume_history(user_id: str, payload: dict[str, Any]) -> None:
    """Writes 12-week completed volume history + `fetched_at` timestamp to 'users/{user_id}/cache/volume_history'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", VOLUME_HISTORY_DOC_ID, payload)


async def save_race_projection(user_id: str, payload: dict[str, Any]) -> None:
    """Writes the cached 12-week race projection to 'users/{user_id}/cache/race_projection'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", RACE_PROJECTION_DOC_ID, payload)


async def delete_race_projection(user_id: str) -> None:
    """Deletes the cached race projection at 'users/{user_id}/cache/race_projection'."""
    await delete_document(f"users/{user_id}/cache", RACE_PROJECTION_DOC_ID)


async def get_cached_year_review(user_id: str, year: int) -> Optional[dict[str, Any]]:
    """Reads the cached calendar-year review from 'users/{user_id}/cache/year_review_{year}'."""
    return await read_document(f"users/{user_id}/cache", year_review_doc_id(year))


async def save_year_review(user_id: str, year: int, payload: dict[str, Any]) -> None:
    """Writes the cached calendar-year review to 'users/{user_id}/cache/year_review_{year}'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", year_review_doc_id(year), payload)


async def get_cached_year_review_raw(user_id: str, year: int) -> Optional[dict[str, Any]]:
    """Reads the compact raw snapshot from 'users/{user_id}/cache/year_review_raw_{year}'."""
    return await read_document(f"users/{user_id}/cache", year_review_raw_doc_id(year))


async def save_year_review_raw(user_id: str, year: int, payload: dict[str, Any]) -> None:
    """Writes the compact raw snapshot to 'users/{user_id}/cache/year_review_raw_{year}'."""
    if not await user_profile_exists(user_id):
        return
    await write_document(f"users/{user_id}/cache", year_review_raw_doc_id(year), payload)


async def get_year_review_index(user_id: str) -> Optional[dict[str, Any]]:
    """Reads the multi-year index from 'users/{user_id}/cache/year_review_index'."""
    return await read_document(f"users/{user_id}/cache", YEAR_REVIEW_INDEX_DOC_ID)


async def upsert_year_review_index(user_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Merges one calendar-year summary entry into 'users/{user_id}/cache/year_review_index' (latest year first)."""
    existing = await get_year_review_index(user_id) or {}
    by_year: dict[int, dict[str, Any]] = {}
    for item in existing.get("years") or []:
        if isinstance(item, dict) and item.get("year") is not None:
            try:
                by_year[int(item["year"])] = dict(item)
            except (TypeError, ValueError):
                continue
    yr = int(entry["year"])
    by_year[yr] = {**entry, "year": yr}
    ordered = [by_year[y] for y in sorted(by_year.keys(), reverse=True)]
    doc = {"version": 1, "years": ordered}
    if await user_profile_exists(user_id):
        await write_document(f"users/{user_id}/cache", YEAR_REVIEW_INDEX_DOC_ID, doc)
    return doc


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
    "cached_runner_id_for_email",
    "remember_email_runner_id",
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
    "save_race_projection",
    "delete_race_projection",
    "get_cached_year_review",
    "save_year_review",
    "get_cached_year_review_raw",
    "save_year_review_raw",
    "get_year_review_index",
    "upsert_year_review_index",
    "year_review_doc_id",
    "year_review_raw_doc_id",
    "save_training_record",
    "list_training_records",
]

