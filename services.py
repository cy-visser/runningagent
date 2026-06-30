import os
import logging
from typing import Any, Optional
from dotenv import load_dotenv

# Load .env file from the same directory as this services.py file
current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

from google.adk.cli.service_registry import get_service_registry
from google.adk.integrations.firestore.firestore_session_service import FirestoreSessionService
from google.adk.sessions.session import Session
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.events.event import Event
from google.cloud import firestore
import google.adk.cli.utils.service_factory as service_factory

# Configure logging
logger = logging.getLogger("google_adk.running_coach.services")

# Sanitization utilities for Firestore compatibility (escapes keys starting with __)
def sanitize_state(state: Any) -> Any:
    if isinstance(state, dict):
        new_dict = {}
        for k, v in state.items():
            new_key = f"_safe_reserved_{k}" if k.startswith("__") else k
            new_dict[new_key] = sanitize_state(v)
        return new_dict
    elif isinstance(state, list):
        return [sanitize_state(item) for item in state]
    return state

def desanitize_state(state: Any) -> Any:
    if isinstance(state, dict):
        new_dict = {}
        for k, v in state.items():
            new_key = k[15:] if k.startswith("_safe_reserved_") else k
            new_dict[new_key] = desanitize_state(v)
        return new_dict
    elif isinstance(state, list):
        return [desanitize_state(item) for item in state]
    return state

class AutoLoadPreviousSessionFirestoreService(FirestoreSessionService):
    def __init__(self, *args, **kwargs):
        # Ensure we use the correct Firestore database 'running-coach'
        if "client" not in kwargs or kwargs["client"] is None:
            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            kwargs["client"] = firestore.AsyncClient(project=project, database="running-coach")
        super().__init__(*args, **kwargs)

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        # If session_id is not explicitly provided, try to load the previous session
        if not session_id:
            logger.info(f"Checking for previous session for app '{app_name}', user '{user_id}'...")
            try:
                sessions_ref = self._get_sessions_ref(app_name, user_id)
                query = sessions_ref.order_by("createTime", direction=firestore.Query.DESCENDING).limit(1)
                docs = await query.get()
                if docs:
                    prev_session_id = docs[0].id
                    logger.info(f"Found previous session '{prev_session_id}'. Loading...")
                    session = await self.get_session(
                        app_name=app_name,
                        user_id=user_id,
                        session_id=prev_session_id
                    )
                    if session:
                        logger.info(f"Successfully loaded previous session '{prev_session_id}'")
                        return session
                    logger.warning(f"Failed to load previous session '{prev_session_id}'")
                else:
                    logger.info("No previous session found in Firestore.")
            except Exception as e:
                logger.error(f"Error loading previous session: {e}", exc_info=True)

        # Fallback to creating a new session
        logger.info("Creating a new session in Firestore...")
        sanitized_state = sanitize_state(state) if state else None
        session = await super().create_session(
            app_name=app_name,
            user_id=user_id,
            state=sanitized_state,
            session_id=session_id
        )
        
        # Desanitize in-memory state
        session.state = desanitize_state(session.state)

        # Add a welcoming message from the coach if it's a brand new session
        try:
            greeting_text = "Hello! I'm your AI running coach, ready to help you achieve your running goals. To start, please tell me your first and last name."
            greeting_event = Event(
                invocation_id=Event.new_id(),
                author=app_name,
                message=greeting_text
            )
            await self.append_event(session, greeting_event)
            logger.info("Appended initial greeting to the new session.")
        except Exception as e:
            logger.error(f"Failed to append initial greeting: {e}", exc_info=True)

        return session

    async def get_session(self, *args, **kwargs) -> Optional[Session]:
        session = await super().get_session(*args, **kwargs)
        if session:
            session.state = desanitize_state(session.state)
        return session

    async def list_sessions(self, *args, **kwargs) -> ListSessionsResponse:
        response = await super().list_sessions(*args, **kwargs)
        for session in response.sessions:
            session.state = desanitize_state(session.state)
        return response

    async def append_event(self, session: Session, event: Event) -> Event:
        # Temporarily sanitize state and state_delta in-place for Firestore write
        orig_session_state = session.state
        session.state = sanitize_state(orig_session_state)
        
        orig_state_delta = None
        if event.actions and event.actions.state_delta:
            orig_state_delta = event.actions.state_delta
            event.actions.state_delta = sanitize_state(orig_state_delta)
            
        try:
            await super().append_event(session, event)
        finally:
            # Restore original desanitized states in-place
            session.state = orig_session_state
            if orig_state_delta is not None:
                event.actions.state_delta = orig_state_delta
                
        return event

# Factory function for the registry
def firestore_session_factory(uri: str, **kwargs):
    from urllib.parse import urlparse
    parsed = urlparse(uri)
    root_collection = parsed.netloc or None
    return AutoLoadPreviousSessionFirestoreService(root_collection=root_collection)

# Register the firestore scheme
get_service_registry().register_session_service("firestore", firestore_session_factory)
logger.info("Registered 'firestore' session service scheme with state sanitization.")

# Monkeypatch create_session_service_from_options to default to firestore://
original_create_session_service = service_factory.create_session_service_from_options

def my_create_session_service(*args, **kwargs):
    if not kwargs.get("session_service_uri"):
        logger.info("No session_service_uri specified. Defaulting to 'firestore://'")
        kwargs["session_service_uri"] = "firestore://"
    return original_create_session_service(*args, **kwargs)

service_factory.create_session_service_from_options = my_create_session_service

import sys
if "google.adk.cli.cli" in sys.modules:
    sys.modules["google.adk.cli.cli"].create_session_service_from_options = my_create_session_service
    logger.info("Applied monkeypatch to google.adk.cli.cli")

if "google.adk.cli.fast_api" in sys.modules:
    sys.modules["google.adk.cli.fast_api"].create_session_service_from_options = my_create_session_service
    logger.info("Applied monkeypatch to google.adk.cli.fast_api")

logger.info("Monkeypatched create_session_service_from_options to default to 'firestore://'.")
