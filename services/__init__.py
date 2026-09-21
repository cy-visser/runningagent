"""External integrations for the running coach agent.

IMPORTANT: importing `session_service` here is load-bearing, not a convenience
re-export. Its module body registers the ``firestore://`` session scheme with the
ADK service registry and patches ``create_session_service_from_options`` to default
to it (see services/session_service.py). Because importing any submodule of this
package executes this file, that registration is guaranteed to happen before the
ADK CLI builds its session service. Removing the import silently disables session
persistence, so keep it even if nothing references the symbols directly.
"""

from . import session_service  # noqa: F401  (imported for registration side effects)
from .firestore import (
    get_user_profile,
    save_checkin_report,
    save_user_profile,
    update_user_profile,
)
from .secrets import inject_production_secrets
from .session_service import AutoLoadPreviousSessionFirestoreService
from .tp_mcp import get_tp_tool
from .weather import geocode_location, get_weather_conditions, get_weather_for_dates

__all__ = [
    "AutoLoadPreviousSessionFirestoreService",
    "geocode_location",
    "get_tp_tool",
    "get_user_profile",
    "get_weather_conditions",
    "get_weather_for_dates",
    "inject_production_secrets",
    "save_checkin_report",
    "save_user_profile",
    "update_user_profile",
]
