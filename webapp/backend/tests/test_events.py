"""Tests for ADK-to-UI SSE event translation."""

from app.events import TurnEventTranslator


def test_translator_whitelists_report_state_and_classifies_checkin():
    tr = TurnEventTranslator()

    # Thinking part -> status thinking (no raw thought text leaked)
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [{"thought": True, "text": "secret plan"}]}}) == [
        ("status", {"phase": "thinking"})
    ]

    # Tool call
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [{"functionCall": {"name": "fetch_checkin_data"}}]}}) == [
        ("tool", {"name": "fetch_checkin_data", "label": "Pulling 14 days of TrainingPeaks data", "state": "start"})
    ]

    # Tool response with both whitelisted checkin_report_data and internal non-whitelisted state keys
    evs = tr.feed(
        {
            "author": "coaching_agent",
            "actions": {
                "stateDelta": {
                    "user_profile": {"email": "private"},
                    "checkin_tables": "| table |",
                    "checkin_report_data": {"version": 1, "ctl": {"current": 62.4}},
                }
            },
            "content": {"parts": [{"functionResponse": {"name": "fetch_checkin_data", "response": {"result": "ok"}}}]},
        }
    )
    assert evs == [
        ("report", {"kind": "checkin", "data": {"version": 1, "ctl": {"current": 62.4}}}),
        ("tool", {"name": "fetch_checkin_data", "label": "Pulling 14 days of TrainingPeaks data", "state": "done"}),
    ]

    # Partial text chunk + final spliced text
    assert tr.feed({"author": "coaching_agent", "partial": True, "content": {"parts": [{"text": "## Check-in"}]}}) == [
        ("delta", {"text": "## Check-in"})
    ]
    assert tr.feed({"author": "coaching_agent", "partial": False, "content": {"parts": [{"text": "## Check-in\nFull"}]}}) == [
        ("message", {"text": "## Check-in\nFull", "kind": "checkin"})
    ]
