"""HTTP passthrough client for the Running Coach ADK app on Vertex AI Agent Runtime (or local ADK server)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Optional
from urllib.parse import quote

import google.auth
from google.auth.transport import requests as google_requests
import httpx

from .settings import Settings

logger = logging.getLogger(__name__)

_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/reasoningEngines/(?P<engine>[^/]+)$"
)
AUTH_EMAIL_STATE_KEY = "user:auth_email"


def resolve_agent_api_base(settings: Settings) -> tuple[str, bool]:
    """Returns `(base_url, requires_gcp_bearer_token)`."""
    if settings.agent_base_url:
        return settings.agent_base_url.rstrip("/"), False
    if not settings.agent_runtime_resource:
        raise RuntimeError(
            "Neither AGENT_BASE_URL nor AGENT_RUNTIME_RESOURCE is configured."
        )
    match = _RESOURCE_RE.match(settings.agent_runtime_resource.strip())
    if not match:
        raise RuntimeError(
            f"Invalid AGENT_RUNTIME_RESOURCE={settings.agent_runtime_resource!r}; "
            "expected projects/{project}/locations/{location}/reasoningEngines/{id}."
        )
    loc = match.group("location")
    resource = settings.agent_runtime_resource.strip()
    return f"https://{loc}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api", True


class AgentRuntimeClient:
    """Calls ADK session and `/run_sse` endpoints with `user_id = web_<email>`."""

    def __init__(self, settings: Settings, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=880.0, write=30.0, pool=15.0)
        )
        self._owns_http = http_client is None
        self._creds: Any = None
        self._creds_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _refresh_token_sync(self) -> str:
        if self._creds is None:
            self._creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        if not self._creds.valid or self._creds.expired or not self._creds.token:
            self._creds.refresh(google_requests.Request())
        return str(self._creds.token)

    async def _headers(self, requires_token: bool) -> dict[str, str]:
        if not requires_token:
            return {}
        async with self._creds_lock:
            token = await asyncio.to_thread(self._refresh_token_sync)
        return {"Authorization": f"Bearer {token}"}

    def _sessions_url(self, base: str, adk_user_id: str, session_id: Optional[str] = None) -> str:
        app = quote(self._settings.agent_app_name, safe="")
        uid = quote(adk_user_id, safe="")
        url = f"{base}/apps/{app}/users/{uid}/sessions"
        if session_id:
            url = f"{url}/{quote(session_id, safe='')}"
        return url

    async def create_session(self, adk_user_id: str, auth_email: str) -> dict[str, Any]:
        base, need_token = resolve_agent_api_base(self._settings)
        headers = {**(await self._headers(need_token)), "Content-Type": "application/json"}
        resp = await self._http.post(
            self._sessions_url(base, adk_user_id),
            headers=headers,
            json={"state": {AUTH_EMAIL_STATE_KEY: auth_email}},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def stream_run_sse(
        self,
        adk_user_id: str,
        session_id: str,
        auth_email: str,
        message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        base, need_token = resolve_agent_api_base(self._settings)
        headers = {
            **(await self._headers(need_token)),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "app_name": self._settings.agent_app_name,
            "user_id": adk_user_id,
            "session_id": session_id,
            "streaming": True,
            "state_delta": {AUTH_EMAIL_STATE_KEY: auth_email},
            "new_message": {"role": "user", "parts": [{"text": message}]},
        }
        async with self._http.stream(
            "POST",
            f"{base}/run_sse",
            params={"alt": "sse"},
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"Agent Runtime returned HTTP {resp.status_code}: {body}")

            data_lines: list[str] = []
            async for raw_line in resp.aiter_lines():
                line = raw_line.rstrip("\r")
                if not line:
                    if data_lines:
                        joined = "\n".join(data_lines)
                        data_lines.clear()
                        if joined != "[DONE]":
                            try:
                                parsed = json.loads(joined)
                                if isinstance(parsed, dict):
                                    yield parsed
                            except json.JSONDecodeError:
                                logger.warning("Ignoring non-JSON SSE payload from agent: %s", joined[:200])
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip(" "))

            if data_lines:
                joined = "\n".join(data_lines)
                if joined != "[DONE]":
                    try:
                        parsed = json.loads(joined)
                        if isinstance(parsed, dict):
                            yield parsed
                    except json.JSONDecodeError:
                        pass
