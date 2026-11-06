"""Firestore repository for web runner profiles and KMS-encrypted TrainingPeaks credentials."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .auth import normalize_email
from .profile_model import ProfileUpdatePayload, apply_profile_edit, profile_state_for
from .settings import Settings
from .trainingpeaks import (
    ConnectConflictError,
    ValidatedTpAccount,
    build_credential_document,
    encrypt_tp_cookie_sync,
)

CREDENTIAL_DOC_ID = "trainingpeaks"
INTERNAL_PROFILE_FIELDS = ("latitude", "longitude")


class ProfileStore:
    """Async Firestore data access for `users/{runner_id}` and `users/{runner_id}/private/trainingpeaks`."""

    def __init__(self, settings: Settings, client: Optional[firestore.AsyncClient] = None) -> None:
        self._settings = settings
        self._client = client

    def _db(self) -> firestore.AsyncClient:
        if self._client is None:
            self._client = firestore.AsyncClient(
                project=self._settings.project_id,
                database=self._settings.firestore_database,
            )
        return self._client

    async def find_by_email(self, email: str) -> Optional[tuple[str, dict[str, Any]]]:
        clean = normalize_email(email)
        if not clean:
            return None
        query = (
            self._db()
            .collection("users")
            .where(filter=FieldFilter("email", "==", clean))
            .limit(2)
        )
        matches = [(snap.id, snap.to_dict() or {}) async for snap in query.stream()]
        if not matches:
            return None
        if len(matches) > 1:
            ids = ", ".join(doc_id for doc_id, _ in matches)
            raise RuntimeError(f"Multiple runner profiles match email {clean!r}: {ids}")
        return matches[0]

    async def get_tp_status(self, runner_id: Optional[str]) -> dict[str, Any]:
        if not runner_id:
            return {"connected": False, "tp_name": None, "updated_at": None}
        snap = await self._db().document(f"users/{runner_id}/private/{CREDENTIAL_DOC_ID}").get()
        if not snap.exists:
            return {"connected": False, "tp_name": None, "updated_at": None}
        data = snap.to_dict() or {}
        connected = bool(data.get("cookie_ciphertext"))
        return {
            "connected": connected,
            "tp_name": data.get("tp_name") if connected else None,
            "updated_at": data.get("updated_at") if connected else None,
        }

    async def connect_trainingpeaks(
        self,
        email: str,
        account: ValidatedTpAccount,
        encrypt_fn: Any = encrypt_tp_cookie_sync,
    ) -> dict[str, Any]:
        clean_email = normalize_email(email)
        if not clean_email:
            raise ValueError("Invalid authenticated email.")
        if not self._settings.tp_cookie_kms_key:
            raise RuntimeError("TP_COOKIE_KMS_KEY is not configured.")

        existing_by_email = await self.find_by_email(clean_email)
        if existing_by_email and existing_by_email[0] != account.runner_id:
            raise ConnectConflictError(
                f"Account {clean_email} is already linked to runner '{existing_by_email[0]}', "
                f"which does not match TrainingPeaks athlete '{account.tp_name}' ({account.runner_id})."
            )

        user_ref = self._db().document(f"users/{account.runner_id}")
        user_snap = await user_ref.get()
        existing_doc = user_snap.to_dict() if user_snap.exists else None
        if existing_doc is not None:
            doc_email = normalize_email(existing_doc.get("email"))
            if doc_email != clean_email:
                raise ConnectConflictError(
                    f"Runner profile '{account.runner_id}' already exists and is not linked to {clean_email}."
                )

        ciphertext = await asyncio.to_thread(
            encrypt_fn,
            self._settings.tp_cookie_kms_key,
            account.runner_id,
            account.cookie,
        )
        cred_doc = build_credential_document(account, ciphertext, linked_email=clean_email, source="web")
        await self._db().document(f"users/{account.runner_id}/private/{CREDENTIAL_DOC_ID}").set(cred_doc)

        if existing_doc is None:
            skeleton = {
                "firstname": account.firstname,
                "lastname": account.lastname,
                "email": clean_email,
                "onboarding_pending": True,
            }
            await user_ref.set(skeleton)
            profile = skeleton
        else:
            profile = existing_doc

        return {
            "connected": True,
            "runner_id": account.runner_id,
            "tp_name": account.tp_name,
            "updated_at": cred_doc["updated_at"],
            "profile_state": profile_state_for(profile),
        }

    async def get_clean_profile(self, email: str) -> Optional[tuple[str, dict[str, Any]]]:
        found = await self.find_by_email(email)
        if not found:
            return None
        runner_id, doc = found
        clean = {k: v for k, v in doc.items() if k not in INTERNAL_PROFILE_FIELDS}
        return runner_id, clean

    async def update_profile(self, email: str, edit: ProfileUpdatePayload) -> tuple[str, dict[str, Any]]:
        found = await self.find_by_email(email)
        if not found:
            raise LookupError("No runner profile is linked to this account yet.")
        runner_id, existing = found
        updates, deleted = apply_profile_edit(existing, edit)
        firestore_patch: dict[str, Any] = dict(updates)
        for field_name in deleted:
            firestore_patch[field_name] = firestore.DELETE_FIELD

        user_ref = self._db().document(f"users/{runner_id}")
        await user_ref.update(firestore_patch)
        refreshed = (await user_ref.get()).to_dict() or {}
        clean = {k: v for k, v in refreshed.items() if k not in INTERNAL_PROFILE_FIELDS}
        return runner_id, clean
