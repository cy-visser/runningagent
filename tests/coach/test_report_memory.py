"""Report memory: report output survives compaction verbatim; each request keeps only the latest copies."""

from google.adk.events.event import Event
from google.adk.flows.llm_flows.contents import _process_compaction_events
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry.sdk.trace import TracerProvider

from running_coach.coach.coaching.model_callbacks import apply_thinking_policy
from running_coach.coach.report_memory import (
    REPORT_MEMORY_HEADER,
    ReportMemorySummarizer,
    keep_latest_reports_and_skills,
)
from running_coach.tests.fakes import FakeContext

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


def test_summary_keeps_the_latest_report_output_verbatim_and_leaves_bulk_out_of_the_prompt():
    import asyncio

    compacted, prompt = asyncio.run(_compact(_session_events()))
    parts = compacted.actions.compaction.compacted_content.parts
    assert parts[0].text == "Runner audited the plan."
    memory = parts[-1].text
    assert memory.startswith(REPORT_MEMORY_HEADER)
    # Verbatim, labelled with tool and arguments; [workout_id]s survive.
    assert AUDIT in memory and "[3937622001]" in memory
    assert 'tool="fetch_schedule_audit_data"' in memory and "start_date=2026-11-02, end_date=2026-11-29" in memory
    # One workout analysis: the latest.
    assert ANALYSIS_NEW in memory and ANALYSIS_OLD not in memory
    # The summarizer LLM never sees report output or skill instructions (no 2,000-char truncation of them).
    assert AUDIT not in prompt and ANALYSIS_NEW not in prompt and "Audit protocol step" not in prompt
    assert "[report output kept verbatim in the report memory]" in prompt and "[skill instructions omitted]" in prompt
    assert "move Wed to Thu" in prompt


def test_compacted_history_reaches_the_model_with_the_report_memory():
    import asyncio

    events = _session_events()
    compacted, _ = asyncio.run(_compact(events))
    later = _event("user", 11.0, "i4", types.Part(text="ok add strength training on Nov 13th"))
    processed = _process_compaction_events([*events, compacted, later])
    texts = [p.text for e in processed for p in (e.content.parts if e.content else []) if p.text]
    assert any("[3937622001]" in t for t in texts)  # the planned strength session is still visible
    assert texts[-1] == "ok add strength training on Nov 13th"


def _summary_content(*blocks: str) -> types.Content:
    memory = "\n\n".join([REPORT_MEMORY_HEADER, *blocks])
    return types.Content(role="user", parts=[
        types.Part(text="For context:"), types.Part(text="[model] said: Runner audited the plan."),
        types.Part(text=f"[model] said: {memory}"),
    ])


def _block(tool: str, text: str) -> str:
    return f'<report tool="{tool}" label="x" run="2026-11-07 12:00 UTC">\n{text}\n</report>'


def test_each_request_keeps_one_copy_of_each_report_and_skill():
    summary = _summary_content(_block("fetch_schedule_audit_data", AUDIT), _block("analyze_workout", ANALYSIS_OLD))
    skill_old = types.Content(role="user", parts=[_resp("load_skill", "s1", {"skill_name": "workout-analysis", "instructions": SKILL_TEXT})])
    analysis_raw = types.Content(role="user", parts=[_resp("analyze_workout", "a1", {"result": ANALYSIS_NEW})])
    skill_new = types.Content(role="user", parts=[_resp("load_skill", "s2", {"skill_name": "workout-analysis", "instructions": SKILL_TEXT})])
    req = LlmRequest(contents=[summary, skill_old, analysis_raw, skill_new,
                               types.Content(role="user", parts=[types.Part(text="Compare with the audit")])])

    assert keep_latest_reports_and_skills(FakeContext(), req) is None
    memory = req.contents[0].parts[-1].text
    assert AUDIT in memory and ANALYSIS_OLD not in memory      # the older analysis block is dropped
    assert req.contents[2].parts[0].function_response.response == {"result": ANALYSIS_NEW}
    old_skill = req.contents[1].parts[0].function_response.response
    assert old_skill["instructions"].startswith("[same instructions")  # one copy of the skill text
    assert req.contents[3].parts[0].function_response.response["instructions"] == SKILL_TEXT
    # The stored history is never changed.
    assert ANALYSIS_OLD in summary.parts[-1].text and skill_old.parts[0].function_response.response["instructions"] == SKILL_TEXT

    # A newer raw audit supersedes the summary block; the older raw response keeps its call paired.
    audit_raw = types.Content(role="user", parts=[_resp("fetch_schedule_audit_data", "r1", {"result": AUDIT + " (rerun)"})])
    req = LlmRequest(contents=[summary, audit_raw])
    keep_latest_reports_and_skills(FakeContext(), req)
    assert all("<report" not in (p.text or "") or "analyze_workout" in p.text for p in req.contents[0].parts)
    assert req.contents[1].parts[0].function_response.response["result"].endswith("(rerun)")


def test_compaction_is_every_10_messages_without_a_token_trigger():
    from running_coach.agent import app

    config = app.events_compaction_config
    assert (config.compaction_interval, config.overlap_size) == (10, 2)
    assert config.token_threshold is None and config.event_retention_size is None
    assert isinstance(config.summarizer, ReportMemorySummarizer)


def test_thinking_level_is_recorded_on_the_span():
    tracer = TracerProvider().get_tracer("test")
    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="How was my week?")])],
                     config=types.GenerateContentConfig())
    with tracer.start_as_current_span("call_llm") as span:
        apply_thinking_policy(FakeContext(), req)
    assert span.attributes["coach.thinking_level"] == "HIGH"
    assert span.attributes["coach.thinking_reason"] == "default"
