"""Report memory: report output survives compaction verbatim; each request keeps only the latest copies."""

from google.adk.events.event import Event
from google.adk.flows.llm_flows.contents import _process_compaction_events
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from running_coach.coach.report_memory import ReportMemorySummarizer

SKILL_TEXT = "# Schedule Audit & Assessment Skill\n" + "Audit protocol step. " * 200
AUDIT = (
    "### Training Schedule Audit\n* Nov 09 - Nov 15: 0 km run\n"
    "  - Fri 13 Nov · Strength · General S&C Work · 45 min [3937622001]"
)
ANALYSIS_OLD = "Workout analysis: Easy Run 2026-11-05, Pa:Hr 3.1%, weather 9°C"
ANALYSIS_NEW = "Workout analysis: Threshold 2026-11-06, 4x2km @ 4:47/km, weather 11°C"


class FakeLlm:
    model = "fake-summarizer"

    def __init__(self):
        self.prompts: list[str] = []

    async def generate_content_async(self, llm_request, stream=False):
        self.prompts.append(llm_request.contents[0].parts[0].text)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Runner audited the plan.")]))


def _call(name: str, call_id: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, id=call_id, args=args))


def _resp(name: str, call_id: str, payload: dict) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(name=name, id=call_id, response=payload))


def _event(author: str, ts: float, inv: str, *parts: types.Part) -> Event:
    role = "model" if author != "user" else "user"
    return Event(author=author, timestamp=ts, invocation_id=inv, content=types.Content(role=role, parts=list(parts)))


def _session_events() -> list[Event]:
    return [
        _event("user", 1.0, "i1", types.Part(text="Audit my schedule")),
        _event("coaching_agent", 2.0, "i1", _call("load_skill", "c1", skill_name="schedule-audit"),
               _call("fetch_schedule_audit_data", "c2", start_date="2026-11-02", end_date="2026-11-29")),
        _event("coaching_agent", 3.0, "i1", _resp("load_skill", "c1", {"skill_name": "schedule-audit", "instructions": SKILL_TEXT}),
               _resp("fetch_schedule_audit_data", "c2", {"result": AUDIT})),
        _event("coaching_agent", 4.0, "i1", types.Part(text="### Assessment ... move Wed to Thu")),
        _event("user", 5.0, "i2", types.Part(text="Analyze Thursday")),
        _event("coaching_agent", 6.0, "i2", _call("analyze_workout", "c3", date_str="2026-11-05")),
        _event("coaching_agent", 7.0, "i2", _resp("analyze_workout", "c3", {"result": ANALYSIS_OLD})),
        _event("user", 8.0, "i3", types.Part(text="And Friday?")),
        _event("coaching_agent", 9.0, "i3", _call("analyze_workout", "c4", date_str="2026-11-06")),
        _event("coaching_agent", 10.0, "i3", _resp("analyze_workout", "c4", {"result": ANALYSIS_NEW})),
    ]


async def _compact(events: list[Event]):
    llm = FakeLlm()
    compacted = await ReportMemorySummarizer(llm=llm).maybe_summarize_events(events=events)
    return compacted, llm.prompts[0]


def test_compacted_history_reaches_the_model_with_the_report_memory():
    import asyncio

    events = _session_events()
    compacted, _ = asyncio.run(_compact(events))
    later = _event("user", 11.0, "i4", types.Part(text="ok add strength training on Nov 13th"))
    processed = _process_compaction_events([*events, compacted, later])
    texts = [p.text for e in processed for p in (e.content.parts if e.content else []) if p.text]
    assert any("[3937622001]" in t for t in texts)  # the planned strength session is still visible
    assert texts[-1] == "ok add strength training on Nov 13th"
