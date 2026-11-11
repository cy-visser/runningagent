"""Pure translation between ADK `/run_sse` / session events and the browser SSE protocol."""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

MessageKind = Literal["checkin", "trend", "workout", "audit", "nutrition", "chat"]

WHITELISTED_REPORT_KEYS: dict[str, Literal["checkin", "trend", "audit", "workout"]] = {
    "checkin_report_data": "checkin",
    "trend_report_data": "trend",
    "audit_report_data": "audit",
    "workout_report_data": "workout",
}

# Staged workout changes (web card with the "Update TrainingPeaks" button) and their application.
# Separate from reports so one coach message can carry both a report and a staged-changes card.
# A staged training plan (plan-builder card, applied week by week) follows the same pattern.
CHANGE_EVENT_KEYS: dict[str, Literal["staged", "applied", "plan_staged", "plan_applied"]] = {
    "staged_workout_changes": "staged",
    "applied_workout_changes": "applied",
    "staged_training_plan": "plan_staged",
    "applied_training_plan": "plan_applied",
}
PLAN_BACKEND_ONLY_KEYS = ("spec", "zones")

TOOL_LABELS: dict[str, str] = {
    "fetch_checkin_data": "Pulling 14 days of TrainingPeaks data",
    "fetch_trend_data": "Analysing 6-month training log & load capacity",
    "analyze_workout": "Analysing workout telemetry & recovery",
    "fetch_plan_audit_data": "Auditing weekly schedule & calendar notes",
    "fetch_nutrition_context": "Loading fueling & weather forecast",
    "stage_workout_changes": "Staging plan changes",
    "apply_staged_changes": "Updating TrainingPeaks",
    "fetch_plan_context": "Reading your training history",
    "stage_training_plan": "Building your plan",
    "apply_training_plan": "Updating TrainingPeaks",
    "get_weather": "Checking local weather forecast",
    "request_new_goal": "Starting goal setup",
    "load_skill": "Loading coaching protocol",
}

TOOL_TO_MESSAGE_KIND: dict[str, MessageKind] = {
    "fetch_checkin_data": "checkin",
    "fetch_trend_data": "trend",
    "analyze_workout": "workout",
    "fetch_plan_audit_data": "audit",
    "fetch_nutrition_context": "nutrition",
}


def label_for_tool(name: str) -> str:
    return TOOL_LABELS.get(name, f"Running {name.replace('_', ' ')}")


def infer_message_kind(tools_used: set[str], report_kind: Optional[str] = None) -> MessageKind:
    if report_kind in ("checkin", "trend", "audit", "workout"):
        return report_kind  # type: ignore[return-value]
    for tool_name in ("fetch_checkin_data", "fetch_trend_data", "analyze_workout", "fetch_plan_audit_data", "fetch_nutrition_context"):
        if tool_name in tools_used:
            return TOOL_TO_MESSAGE_KIND[tool_name]
    return "chat"


def format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Coded replies of the agent's tools (`renderUiWidgets`; contract in running_coach/shared/ui_channel.py).
UI_PROVIDER = "running_coach"
REPLY = "reply"


def _reply_texts(adk_event: dict[str, Any]) -> list[str]:
    actions = adk_event.get("actions")
    widgets = (actions.get("renderUiWidgets") or actions.get("render_ui_widgets")) if isinstance(actions, dict) else None
    texts = []
    for widget in widgets if isinstance(widgets, list) else []:
        payload = widget.get("payload") if isinstance(widget, dict) else None
        if widget.get("provider") == UI_PROVIDER and isinstance(payload, dict) and payload.get("kind") == REPLY:
            text = (payload.get("data") or {}).get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return texts


def _extract_state_delta(adk_event: dict[str, Any]) -> dict[str, Any]:
    actions = adk_event.get("actions")
    if not isinstance(actions, dict):
        return {}
    sd = actions.get("stateDelta") or actions.get("state_delta")
    return sd if isinstance(sd, dict) else {}


class TurnEventTranslator:
    """Stateful per-turn translator turning raw ADK SSE JSON events into UI `(event_name, payload)` pairs."""

    def __init__(self) -> None:
        self.tools_used: set[str] = set()
        self.report_kind: Optional[str] = None
        self._thinking_emitted: bool = False
        # Final texts of this turn's model responses: a turn can hold several (e.g. recommendations,
        # then the coded "changes staged" line), and the bubble shows all of them.
        self._final_texts: list[str] = []
        self._delta_open: bool = False

    def feed(self, adk_event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []

        err = adk_event.get("errorMessage") or adk_event.get("error_message")
        if err:
            out.append(("error", {"message": str(err)}))
            return out

        state_delta = _extract_state_delta(adk_event)
        for state_key, r_kind in WHITELISTED_REPORT_KEYS.items():
            payload = state_delta.get(state_key)
            if isinstance(payload, dict):
                self.report_kind = r_kind
                out.append(("report", {"kind": r_kind, "data": payload}))
        for state_key, ev_name in CHANGE_EVENT_KEYS.items():
            payload = state_delta.get(state_key)
            if isinstance(payload, dict):
                if ev_name == "plan_staged":
                    # The plan spec and zones are backend-only (re-expanded at apply time).
                    payload = {k: v for k, v in payload.items() if k not in PLAN_BACKEND_ONLY_KEYS}
                out.append((ev_name, payload))

        author = str(adk_event.get("author") or "")
        if author == "user":
            return out

        content = adk_event.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return self._add_replies(adk_event, out)

        is_partial = bool(adk_event.get("partial"))
        visible_texts: list[str] = []

        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("thought"):
                if not self._thinking_emitted:
                    self._thinking_emitted = True
                    out.append(("status", {"phase": "thinking"}))
                continue

            fn_call = part.get("functionCall") or part.get("function_call")
            if isinstance(fn_call, dict) and fn_call.get("name"):
                t_name = str(fn_call["name"])
                self.tools_used.add(t_name)
                self._thinking_emitted = False
                out.append(("tool", {"name": t_name, "label": label_for_tool(t_name), "state": "start"}))
                continue

            fn_resp = part.get("functionResponse") or part.get("function_response")
            if isinstance(fn_resp, dict) and fn_resp.get("name"):
                t_name = str(fn_resp["name"])
                self.tools_used.add(t_name)
                out.append(("tool", {"name": t_name, "label": label_for_tool(t_name), "state": "done"}))
                continue

            text = part.get("text")
            if isinstance(text, str) and text:
                visible_texts.append(text)

        if visible_texts:
            joined = "".join(visible_texts)
            if is_partial:
                if self._final_texts and not self._delta_open:
                    joined = "\n\n" + joined  # a new response after an earlier one in this turn
                self._delta_open = True
                out.append(("delta", {"text": joined}))
            else:
                if not self._final_texts or self._final_texts[-1] != joined:
                    self._final_texts.append(joined)
                self._delta_open = False
                kind = infer_message_kind(self.tools_used, self.report_kind)
                out.append(("message", {"text": "\n\n".join(self._final_texts), "kind": kind}))
                self._thinking_emitted = False

        return self._add_replies(adk_event, out)

    def _add_replies(self, adk_event: dict[str, Any], out: list) -> list[tuple[str, dict[str, Any]]]:
        """A tool's coded reply joins the turn's message, after any text the coach wrote."""
        replies = _reply_texts(adk_event)
        if replies:
            self._final_texts.extend(replies)
            kind = infer_message_kind(self.tools_used, self.report_kind)
            out.append(("message", {"text": "\n\n".join(self._final_texts), "kind": kind}))
        return out
