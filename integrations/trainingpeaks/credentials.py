"""Per-runner TrainingPeaks cookies: `users/{runner_id}/private/trainingpeaks`, encrypted with Cloud KMS.

The cookie never enters session state, LLM context, logs, or traces. It is decrypted in memory
and passed only to that runner's `tp-mcp` subprocess. There is no shared cookie.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from typing import Any, Optional

from google.cloud import kms

from ..config import dev_runner_email, tp_cookie_kms_key
from ..firestore import find_user_profile_by_email, read_document
from ...utils.profile_helpers import profile_user_id

logger = logging.getLogger(__name__)

CREDENTIAL_DOC_ID = "trainingpeaks"
DOC_CACHE_TTL_S = 60.0

_kms_client: Optional[kms.KeyManagementServiceClient] = None
_doc_cache: dict[str, tuple[float, Optional[bytes]]] = {}
_decrypt_cache: dict[str, str] = {}


class TrainingPeaksNotConnected(RuntimeError):
    """Raised when a runner has no connected TrainingPeaks credential."""


def credential_aad(runner_id: str) -> bytes:
    """Additional authenticated data binding ciphertext to a single runner document."""
    return f"users/{runner_id}".encode("utf-8")


def _get_kms_client() -> kms.KeyManagementServiceClient:
    global _kms_client
    if _kms_client is None:
        _kms_client = kms.KeyManagementServiceClient()
    return _kms_client


def clear_tp_credential_cache() -> None:
    """Clears in-memory document and plaintext caches (used in tests and after errors)."""
    _doc_cache.clear()
    _decrypt_cache.clear()


def _coerce_ciphertext(raw: Any) -> Optional[bytes]:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = bytes(raw)
        return data or None
    if isinstance(raw, str) and raw.strip():
        try:
            data = base64.b64decode(raw.strip())
            return data or None
        except ValueError:
            return None
    return None


async def _load_ciphertext(runner_id: str) -> Optional[bytes]:
    now = time.monotonic()
    cached = _doc_cache.get(runner_id)
    if cached and cached[0] > now:
        return cached[1]

    doc = await read_document(f"users/{runner_id}/private", CREDENTIAL_DOC_ID)
    ciphertext = _coerce_ciphertext((doc or {}).get("cookie_ciphertext"))
    _doc_cache[runner_id] = (now + DOC_CACHE_TTL_S, ciphertext)
    return ciphertext


def _decrypt_ciphertext_sync(runner_id: str, ciphertext: bytes) -> str:
    key_name = tp_cookie_kms_key()
    if not key_name:
        raise RuntimeError("TP_COOKIE_KMS_KEY (or GOOGLE_CLOUD_PROJECT) is not configured.")
    response = _get_kms_client().decrypt(
        request={
            "name": key_name,
            "ciphertext": ciphertext,
            "additional_authenticated_data": credential_aad(runner_id),
        }
    )
    return response.plaintext.decode("utf-8").strip()


async def get_runner_tp_cookie(runner_id: Optional[str]) -> Optional[str]:
    """Reads and KMS-decrypts `users/{runner_id}/private/trainingpeaks`, or returns None."""
    if not runner_id:
        return None
    ciphertext = await _load_ciphertext(runner_id)
    if not ciphertext:
        return None

    digest = hashlib.sha256(credential_aad(runner_id) + b":" + ciphertext).hexdigest()
    if digest in _decrypt_cache:
        return _decrypt_cache[digest]

    cookie = await asyncio.to_thread(_decrypt_ciphertext_sync, runner_id, ciphertext)
    if not cookie:
        return None
    _decrypt_cache[digest] = cookie
    return cookie


async def has_tp_credential(runner_id: Optional[str]) -> bool:
    """True when `users/{runner_id}/private/trainingpeaks` holds an encrypted cookie."""
    if not runner_id:
        return False
    return bool(await _load_ciphertext(runner_id))


async def get_tp_cookie_for_email(email: str) -> Optional[str]:
    """Resolves a runner profile by email and returns its decrypted TrainingPeaks cookie."""
    found = await find_user_profile_by_email(email)
    if not found:
        return None
    return await get_runner_tp_cookie(found[0])


async def resolve_tp_cookie(state: Any) -> str:
    """Resolves the active runner's TrainingPeaks cookie from session state (or local DEV_RUNNER_EMAIL)."""
    profile = state.get("user_profile") if state is not None else None
    runner_id = profile_user_id(profile) if isinstance(profile, dict) else None
    cookie = await get_runner_tp_cookie(runner_id) if runner_id else None
    if not cookie and (dev_email := dev_runner_email()):
        cookie = await get_tp_cookie_for_email(dev_email)
    if not cookie:
        raise TrainingPeaksNotConnected("TrainingPeaks is not connected for this runner.")
    return cookie
