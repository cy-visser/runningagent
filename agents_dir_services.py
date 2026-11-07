"""ADK `services.py` for the deployed container: copied to /app/agents/services.py by the Dockerfile.

`adk api_server /app/agents` imports the top-level `services` module from the agents directory BEFORE
it creates the session service from SESSION_SERVICE_URI (firestore://...) and before it loads the agent.
Importing the integrations package registers the firestore:// session scheme in time. Without this file
the server fails at startup with "Can't load plugin: sqlalchemy.dialects:firestore".
"""

import running_coach.integrations  # noqa: F401  (registers the firestore:// session service)
