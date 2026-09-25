"""External integrations for the running coach agent.

IMPORTANT: importing `session_service` here is load-bearing, not a convenience
re-export. Its module body registers the ``firestore://`` session scheme with the
ADK service registry and patches ``create_session_service_from_options`` to default
to it (see services/session_service.py). Because importing any submodule of this
package executes this file, that registration is guaranteed to happen before the
ADK CLI builds its session service. Removing the import silently disables session
persistence, so keep it even if nothing references the symbols directly.

Callers import from the submodules directly (e.g. ``.services.firestore``).
"""

from . import session_service  # noqa: F401  (imported for registration side effects)
