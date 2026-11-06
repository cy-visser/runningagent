"""Shared fake profile store, agent client, and test app builder for FastAPI web backend tests."""

from __future__ import annotations

import os
import sys
from typing import Any, AsyncIterator, Optional

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
if os.path.dirname(__file__) not in sys.path:
    sys.path.insert(0, os.path.dirname(__file__))

from app.main import create_app
from app.profile_model import ProfileUpdatePayload, apply_profile_edit, profile_state_for
from app.profiles import ConnectConflictError
from app.settings import Settings
from app.trainingpeaks import ValidatedTpAccount

EMAIL = "cyrille@cyvisser.altostrat.com"
AUDIENCE = "/projects/840839653849/locations/europe-west4/services/running-coach-web"


class FakeProfileStore:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.creds: dict[str, dict[str, Any]] = {}

    async def find_by_email(self, email: str) -> Optional[tuple[str, dict[str, Any]]]:
        for rid, doc in self.users.items():
            if (doc.get("email") or "").lower() == email.lower():
                return rid, dict(doc)
        return None

    async def get_tp_status(self, runner_id: Optional[str]) -> dict[str, Any]:
        cred = self.creds.get(runner_id or "")
        if not cred:
            return {"connected": False, "tp_name": None, "updated_at": None}
        return {"connected": True, "tp_name": cred["tp_name"], "updated_at": cred["updated_at"]}

    async def connect_trainingpeaks(self, email: str, account: ValidatedTpAccount) -> dict[str, Any]:
        by_email = await self.find_by_email(email)
        if by_email and by_email[0] != account.runner_id:
            raise ConnectConflictError("Email already linked to a different athlete.")
        existing = self.users.get(account.runner_id)
        if existing is not None and (existing.get("email") or "").lower() != email.lower():
            raise ConnectConflictError("Runner profile already exists with a different email.")
        self.creds[account.runner_id] = {"tp_name": account.tp_name, "updated_at": "2026-11-05T12:00:00Z"}
        if existing is None:
            self.users[account.runner_id] = {
                "firstname": account.firstname,
                "lastname": account.lastname,
                "email": email,
                "onboarding_pending": True,
            }
        return {
            "connected": True,
            "runner_id": account.runner_id,
            "tp_name": account.tp_name,
            "updated_at": "2026-11-05T12:00:00Z",
            "profile_state": profile_state_for(self.users[account.runner_id]),
        }

    async def get_clean_profile(self, email: str) -> Optional[tuple[str, dict[str, Any]]]:
        return await self.find_by_email(email)

    async def update_profile(self, email: str, edit: ProfileUpdatePayload) -> tuple[str, dict[str, Any]]:
        found = await self.find_by_email(email)
        if not found:
            raise LookupError("Not found")
        rid, existing = found
        updates, deleted = apply_profile_edit(existing, edit, today_iso="2026-11-05")
        merged = {**existing, **updates}
        for k in deleted:
            merged.pop(k, None)
        self.users[rid] = merged
        return rid, dict(merged)


class FakeAgentClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.created_sessions: int = 0

    async def create_session(self, adk_user_id: str, auth_email: str) -> dict[str, Any]:
        self.created_sessions += 1
        return {"id": f"sess-new-{self.created_sessions}", "events": []}

    async def stream_run_sse(
        self,
        adk_user_id: str,
        session_id: str,
        auth_email: str,
        message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(
            {
                "user_id": adk_user_id,
                "session_id": session_id,
                "auth_email": auth_email,
                "message": message,
            }
        )
        yield {"author": "coaching_agent", "partial": True, "content": {"parts": [{"text": "Coach "}]}}
        yield {"author": "coaching_agent", "partial": False, "content": {"parts": [{"text": "Coach reply"}]}}


def build_test_app():
    settings = Settings(
        auth_mode="iap",
        iap_audience=AUDIENCE,
        dev_user_email=None,
        project_id="firestore-cyvisser",
        firestore_database="running-coach",
        tp_cookie_kms_key="projects/p/locations/europe-west4/keyRings/r/cryptoKeys/k",
        agent_runtime_resource="projects/1/locations/europe-west4/reasoningEngines/2",
        agent_base_url=None,
        agent_app_name="running_coach",
        static_dir="/tmp/nonexistent-static",
        k_service=None,
    )
    store = FakeProfileStore()
    agent = FakeAgentClient()
    app = create_app(settings=settings, profile_store=store, agent_client=agent)  # type: ignore[arg-type]

    def fake_verify(assertion: str, audience: str) -> dict[str, Any]:
        if assertion == "valid-jwt":
            return {"iss": "https://cloud.google.com/iap", "aud": audience, "email": EMAIL}
        raise ValueError("bad token")

    async def fake_tp_validate(cookie: str) -> ValidatedTpAccount:
        return ValidatedTpAccount(
            cookie=cookie,
            firstname="Cyrille",
            lastname="Visser",
            runner_id="cyrille_visser",
            tp_name="Cyrille Visser",
            tp_user_id=1,
            tp_athlete_id=2,
        )

    app.state.iap_verifier = fake_verify
    app.state.tp_validator = fake_tp_validate
    return app, store, agent
