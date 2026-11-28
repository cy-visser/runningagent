from google.adk import Workflow
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.plugins.auto_tracing_plugin import AutoTracingPlugin

from .coach.coaching.coaching_agent import coaching_node
from .coach.coaching.quick_actions import QuickActionPlugin
from .coach.model_config import ONBOARDING_MODEL, build_model
from .coach.report_memory import ReportMemorySummarizer
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
    # QuickActionPlugin: web quick actions arrive as a message part (Agent Runtime drops state_delta).
    plugins=[AutoTracingPlugin(), QuickActionPlugin()],
    # Token-threshold session compaction (retains the latest 6 raw events verbatim so warm sessions
    # under 20k tokens keep their prefix KV cache intact and never summarize the active turn).
    # A Workflow root needs an explicit summarizer model; ReportMemorySummarizer preserves the
    # latest report output verbatim (coach/report_memory.py).
    events_compaction_config=EventsCompactionConfig(
        token_threshold=20_000,
        event_retention_size=6,
        summarizer=ReportMemorySummarizer(llm=build_model(ONBOARDING_MODEL)),
    ),
)
