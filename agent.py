from google.adk import Workflow
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.plugins.auto_tracing_plugin import AutoTracingPlugin

from .coach.coaching.coaching_agent import coaching_node
from .coach.model_config import ONBOARDING_MODEL, build_model
from .coach.onboarding.onboarding_agent import onboarding_node
from .coach.profile_router import (
    ROUTE_COACHING,
    ROUTE_NOT_LINKED,
    ROUTE_ONBOARDING,
    ROUTE_TP_NOT_CONNECTED,
    ROUTE_UNAVAILABLE,
    not_linked_node,
    profile_router,
    profile_unavailable_node,
    tp_not_connected_node,
)

root_agent = Workflow(
    name="running_coach_workflow",
    edges=[
        ("START", profile_router),
        (
            profile_router,
            {
                ROUTE_ONBOARDING: onboarding_node,
                ROUTE_COACHING: coaching_node,
                ROUTE_NOT_LINKED: not_linked_node,
                ROUTE_TP_NOT_CONNECTED: tp_not_connected_node,
                ROUTE_UNAVAILABLE: profile_unavailable_node,
            },
        ),
    ],
)

app = App(
    name="running_coach",
    root_agent=root_agent,
    plugins=[AutoTracingPlugin()],
    # Compact session history; a Workflow root needs an explicit summarizer model.
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=10,
        overlap_size=2,
        summarizer=LlmEventSummarizer(llm=build_model(ONBOARDING_MODEL)),
    ),
)
