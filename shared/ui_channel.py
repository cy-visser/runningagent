"""Coded replies of tools: shown to the runner as a UI widget, never sent to the model.

`reply()` attaches the text to the tool's response event (`actions.render_ui_widgets`; the web BFF shows it as
the coach's message) and ends the turn: with `skip_summarization` no LLM call follows the tool.
"""

import uuid

from google.adk.events.ui_widget import UiWidget
from google.adk.tools import ToolContext

UI_PROVIDER = "running_coach"
REPLY = "reply"  # payload data: {"text": Markdown} (contract with webapp/backend/app/events.py)


def reply(tool_context: ToolContext, text: str) -> None:
    call_id = getattr(tool_context, "function_call_id", None) or uuid.uuid4().hex
    tool_context.render_ui_widget(
        UiWidget(id=f"{REPLY}:{call_id}", provider=UI_PROVIDER, payload={"kind": REPLY, "data": {"text": text}})
    )
    tool_context.actions.skip_summarization = True
