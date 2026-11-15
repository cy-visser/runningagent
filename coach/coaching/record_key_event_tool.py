"""`record_key_event`: the coach saves a training-relevant event to its hidden memory (`key_events`)."""

from google.adk.tools import FunctionTool, ToolContext

from ...shared.dates import get_today_date
from ...shared.key_events import SOURCE_COACH, make_event, save_key_event


async def record_key_event(tool_context: ToolContext, event_type: str, date_str: str, summary: str) -> str:
    """Silently saves a key event (`event_type`: race|injury|illness|break|life|other; `date_str`: YYYY-MM-DD|'today'; `summary`: 1 factual line with numbers)."""
    day = get_today_date() if str(date_str or "").strip().lower() == "today" else date_str
    try:
        event = make_event(event_type, day, summary, SOURCE_COACH)
    except ValueError as e:
        return f"Error: {e}"
    profile = tool_context.state.get("user_profile") or {}
    if not await save_key_event(tool_context, profile, event):
        return "Error: the event could not be saved; continue coaching without mentioning it."
    return "Recorded. Do not mention saving it to the runner."


record_key_event_tool = FunctionTool(record_key_event)
