"""External integrations for the running coach agent. Import from the submodules."""

# Registers the firestore:// session scheme and makes it the ADK default. Do not remove.
from . import session_service  # noqa: F401
