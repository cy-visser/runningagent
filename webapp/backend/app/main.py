"""FastAPI backend + static SPA host for the Cloud Run Running Coach web app."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent_client import AgentRuntimeClient
from .auth import AuthenticatedUser, current_user, derive_initials
from .events import TurnEventTranslator, format_sse
from .profile_model import ProfileUpdatePayload, profile_state_for, summarize_profile
from .profiles import ProfileStore
from .settings import Settings, load_settings, validate_startup_settings
from .trainingpeaks import (
    ConnectConflictError,
    TrainingPeaksValidationError,
    validate_tp_cookie,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 15.0

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class ConnectTpRequest(BaseModel):
    cookie: str = Field(..., min_length=8, max_length=8192)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = Field(default=None, max_length=200)


def create_app(
    settings: Optional[Settings] = None,
    profile_store: Optional[ProfileStore] = None,
    agent_client: Optional[AgentRuntimeClient] = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        validate_startup_settings(app.state.settings)
        yield
        client: Optional[AgentRuntimeClient] = getattr(app.state, "agent_client", None)
        if client is not None and agent_client is None:
            await client.aclose()

    app = FastAPI(
        title="AI Running Coach Web App",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.profile_store = profile_store or ProfileStore(resolved_settings)
    app.state.agent_client = agent_client or AgentRuntimeClient(resolved_settings)
    app.state.tp_validator = validate_tp_cookie

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    def _store(request: Request) -> ProfileStore:
        return request.app.state.profile_store

    def _agent(request: Request) -> AgentRuntimeClient:
        return request.app.state.agent_client

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me")
    async def get_me(
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        store = _store(request)
        found = await store.find_by_email(user.email)
        runner_id = found[0] if found else None
        profile = found[1] if found else None
        tp = await store.get_tp_status(runner_id)
        p_state = profile_state_for(profile)
        summary = summarize_profile(profile)
        display_name = (
            (summary or {}).get("full_name")
            or tp.get("tp_name")
            or user.email.split("@", 1)[0]
        )
        initials = derive_initials(
            (profile or {}).get("firstname"),
            (profile or {}).get("lastname"),
            user.email,
        )
        return {
            "email": user.email,
            "runner_id": runner_id,
            "display_name": display_name,
            "initials": initials,
            "profile_state": p_state,
            "tp": tp,
            "summary": summary,
        }

    @app.post("/api/trainingpeaks/connect")
    async def connect_tp(
        body: ConnectTpRequest,
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        validator = request.app.state.tp_validator
        try:
            account = await validator(body.cookie)
        except TrainingPeaksValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

        try:
            return await _store(request).connect_trainingpeaks(user.email, account)
        except ConnectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/api/profile")
    async def get_profile(
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        store = _store(request)
        found = await store.get_clean_profile(user.email)
        if not found:
            raise HTTPException(status_code=404, detail="No runner profile is linked to this account yet.")
        runner_id, profile = found
        tp = await store.get_tp_status(runner_id)
        return {
            "runner_id": runner_id,
            "profile_state": profile_state_for(profile),
            "tp": tp,
            "profile": profile,
        }

    @app.put("/api/profile")
    async def put_profile(
        body: ProfileUpdatePayload,
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        store = _store(request)
        try:
            runner_id, updated = await store.update_profile(user.email, body)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        tp = await store.get_tp_status(runner_id)
        return {
            "runner_id": runner_id,
            "profile_state": profile_state_for(updated),
            "tp": tp,
            "profile": updated,
            "summary": summarize_profile(updated),
        }

    @app.post("/api/session/new")
    async def create_new_session(
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        session = await _agent(request).create_session(user.adk_user_id, user.email)
        return {
            "session_id": session.get("id"),
            "messages": [],
        }

    @app.post("/api/chat")
    async def chat_sse(
        body: ChatRequest,
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> StreamingResponse:
        agent = _agent(request)
        session_id = (body.session_id or "").strip()
        if not session_id:
            session = await agent.create_session(user.adk_user_id, user.email)
            session_id = str(session.get("id") or "")
        if not session_id:
            raise HTTPException(status_code=502, detail="Could not establish an agent session.")

        async def event_generator() -> AsyncIterator[str]:
            translator = TurnEventTranslator()
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            async def pump_agent() -> None:
                try:
                    await queue.put(format_sse("session", {"session_id": session_id}))
                    async for adk_ev in agent.stream_run_sse(
                        adk_user_id=user.adk_user_id,
                        session_id=session_id,
                        auth_email=user.email,
                        message=body.message.strip(),
                    ):
                        for ev_name, payload in translator.feed(adk_ev):
                            await queue.put(format_sse(ev_name, payload))
                except Exception as exc:
                    logger.exception("Error streaming from Agent Runtime")
                    await queue.put(format_sse("error", {"message": str(exc)}))
                finally:
                    await queue.put(format_sse("done", {"session_id": session_id}))
                    await queue.put(None)

            producer = asyncio.create_task(pump_agent())
            try:
                while True:
                    if await request.is_disconnected():
                        producer.cancel()
                        break
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL_S)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if chunk is None:
                        break
                    yield chunk
            finally:
                if not producer.done():
                    producer.cancel()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    static_root = Path(resolved_settings.static_dir)
    if static_root.is_dir() and (static_root / "index.html").is_file():
        assets_dir = static_root / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (static_root / full_path).resolve()
            if full_path and candidate.is_file() and static_root.resolve() in candidate.parents:
                return FileResponse(str(candidate))
            return FileResponse(str(static_root / "index.html"))

    return app


app = create_app()
