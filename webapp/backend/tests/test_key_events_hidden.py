"""Behavioural test: the coach's `key_events` memory is never sent to the browser and survives profile edits."""

from __future__ import annotations

import asyncio
from typing import Any

from app.events import TurnEventTranslator
from app.profile_model import ProfileUpdatePayload
from app.profiles import ProfileStore

EVENTS = [{"date": "2026-11-02", "type": "injury", "summary": "Left calf strain", "source": "coach"}]


def test_record_key_event_never_shows_a_tool_chip():
    tr = TurnEventTranslator()
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [
        {"functionCall": {"name": "record_key_event", "args": {}}}]}}) == []
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [
        {"functionResponse": {"name": "record_key_event", "response": {}}}]}}) == []
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [{"text": "Sorry about the calf."}]}}) == [
        ("message", {"text": "Sorry about the calf.", "kind": "chat"})]


class _Doc:
    def __init__(self, db: dict[str, dict[str, Any]], runner_id: str) -> None:
        self._db, self._id = db, runner_id
        self.patches: list[dict[str, Any]] = []

    async def update(self, patch: dict[str, Any]) -> None:
        self.patches.append(patch)
        self._db[self._id].update(patch)

    async def get(self):
        doc = dict(self._db[self._id])
        return type("Snap", (), {"to_dict": lambda _self: doc})()


class _Client:
    def __init__(self, db: dict[str, dict[str, Any]]) -> None:
        self.db, self.docs = db, {}

    def document(self, path: str) -> _Doc:
        runner_id = path.split("/", 1)[1]
        return self.docs.setdefault(runner_id, _Doc(self.db, runner_id))


def test_key_events_are_hidden_from_profile_responses_and_kept_on_edit():
    db = {"cyrille_visser": {
        "firstname": "Cyrille", "lastname": "Visser", "email": "cyrille@example.com", "location": "Amsterdam",
        "goal_type": "single", "training_goal": "Sub-3:20 Marathon", "timeline": "2027-04-11",
        "goal_set_date": "2026-11-01", "latitude": 52.37, "longitude": 4.89, "key_events": list(EVENTS),
    }}
    client = _Client(db)
    store = ProfileStore(settings=None, client=client)  # type: ignore[arg-type]

    async def find_by_email(email: str):
        return "cyrille_visser", dict(db["cyrille_visser"])

    store.find_by_email = find_by_email  # type: ignore[method-assign]

    _, clean = asyncio.run(store.get_clean_profile("cyrille@example.com"))
    assert "key_events" not in clean and "latitude" not in clean
    assert clean["training_goal"] == "Sub-3:20 Marathon"

    edit = ProfileUpdatePayload(location="Amsterdam", goal_type="single", training_goal="Sub-3:15 Marathon",
                                timeline="2027-04-11", injuries="Calf: recovering")
    _, updated = asyncio.run(store.update_profile("cyrille@example.com", edit))
    assert "key_events" not in updated
    patch = client.docs["cyrille_visser"].patches[0]
    assert "key_events" not in patch                     # never written by a web edit...
    assert db["cyrille_visser"]["key_events"] == EVENTS  # ...so the coach's memory is preserved
    assert db["cyrille_visser"]["training_goal"] == "Sub-3:15 Marathon"
