"""Tool that applies ONE week of the staged training plan to TrainingPeaks (pure code, no reasoning).

The web app calls it once per week (silent quick actions), so a 24-week plan never writes in one burst
and the card shows live progress. Each call re-expands the week from the stored spec and zones, re-reads
that week's calendar (it may have changed since staging), diffs and writes at most WRITE_CONCURRENCY
changes at a time, backing off on 429s. A week already in `weeks_done` is a no-op, so an interrupted
apply resumes where it stopped.
"""

import asyncio
import json
import re
from datetime import timedelta
from typing import Any

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date, parse_date
from ...shared.ui_channel import reply
from ...shared.workout_upsert import write_change
from .helpers.plan_diff import diff_week, write_change as plan_write_change
from .helpers.plan_expand import cutoff_date, expand_week, week_monday
from .helpers.plan_summary_text import (
    NOTHING_STAGED_TEXT,
    REPLACED_TEXT,
    applied_text,
    week_failed_text,
    week_not_found_text,
)
from .helpers.web_payload import (
    APPLIED_PLAN_STATE_KEY,
    STAGED_PLAN_STATE_KEY,
    applied_after_week,
    new_applied,
)

WRITE_CONCURRENCY = 3
BACKOFF_SECONDS = (2, 4, 8)
_RATE_LIMITED = re.compile(r"\b429\b|too many requests", re.IGNORECASE)
_sleep = asyncio.sleep  # module-level so tests can skip the real backoff


async def _write_with_backoff(tool_context: ToolContext, change: dict, gate: asyncio.Semaphore) -> dict:
    """One TrainingPeaks write; a 429 is retried after 2, 4 and 8 seconds (outside the concurrency gate)."""
    for delay in (*BACKOFF_SECONDS, None):
        async with gate:
            result = await write_change(tool_context, change)
        if result.get("ok") or delay is None or not _RATE_LIMITED.search(str(result.get("error") or "")):
            return result
        await _sleep(delay)
    return result


def _finish(tool_context: ToolContext, staged: dict, applied: dict, week: int, text: str = "") -> None:
    """Intermediate weeks end silently (the card shows progress); the last week (or the last missing one)
    replies with the coded confirmation; a failed week says so (the web offers Resume)."""
    last = max(w["week"] for w in staged["weeks"])
    if applied["done"] or week == last:
        text = "\n\n".join(t for t in (text, applied_text(applied, staged)) if t)
    if text:
        reply(tool_context, text)
    tool_context.actions.skip_summarization = True


async def apply_training_plan(tool_context: ToolContext, staged_id: str, week: int) -> str:
    """Applies one week of the staged training plan to TrainingPeaks. Called by the Apply to TrainingPeaks
    button, one week at a time; the app confirms the result to the runner itself.

    Args:
        staged_id: The staged plan's id.
        week: The plan week to write (1 = the first week).
    """
    state = tool_context.state
    staged = state.get(STAGED_PLAN_STATE_KEY)
    if not isinstance(staged, dict) or not staged.get("weeks"):
        reply(tool_context, NOTHING_STAGED_TEXT)
        return json.dumps({"success": False, "reason": "nothing_staged"})
    if staged_id != staged.get("staged_id"):
        reply(tool_context, REPLACED_TEXT)
        return json.dumps({"success": False, "reason": "replaced"})
    week = int(week)
    spec_week = next((w for w in staged["spec"]["weeks"] if w["week"] == week), None)
    if spec_week is None:
        reply(tool_context, week_not_found_text(week))
        return json.dumps({"success": False, "reason": "week_not_found"})
    applied = state.get(APPLIED_PLAN_STATE_KEY)
    if not isinstance(applied, dict) or applied.get("staged_id") != staged_id:
        applied = new_applied(staged)
    if week in applied["weeks_done"]:
        tool_context.actions.skip_summarization = True  # idempotent: a resumed loop may resend a week
        return json.dumps({"success": True, "week": week, "skipped": "already applied", APPLIED_PLAN_STATE_KEY: applied})

    spec = staged["spec"]
    monday = week_monday(spec, week)
    expanded = expand_week(spec_week, monday, staged["zones"], cutoff_date(spec, get_today_date()))
    try:
        workouts = await tp_calls.fetch_workouts(tool_context, iso_date(monday), iso_date(monday + timedelta(days=6)))
    except Exception as e:  # never diff against a calendar we could not read (it would create duplicates)
        applied = applied_after_week(applied, staged, week, {}, 1)
        state[APPLIED_PLAN_STATE_KEY] = applied
        _finish(tool_context, staged, applied, week, week_failed_text(week, [f"calendar not readable: {e}"]))
        return json.dumps({"success": False, "week": week, "reason": "calendar_unavailable", APPLIED_PLAN_STATE_KEY: applied})

    changes = [c for c in (plan_write_change(d) for d in diff_week(expanded, workouts, spec["mode"])) if c]
    gate = asyncio.Semaphore(WRITE_CONCURRENCY)
    results = list(await asyncio.gather(*(_write_with_backoff(tool_context, c, gate) for c in changes)))
    ok: dict[str, int] = {}
    for r in results:
        if r.get("ok"):
            ok[r["action"]] = ok.get(r["action"], 0) + 1
    errors = [f"{parse_date(r['date']).strftime('%a')} {r.get('title')}: {r.get('error')}"
              for r in results if not r.get("ok")]
    applied = applied_after_week(applied, staged, week, ok, len(errors))
    state[APPLIED_PLAN_STATE_KEY] = applied
    _finish(tool_context, staged, applied, week, week_failed_text(week, errors) if errors else "")
    result: dict[str, Any] = {"success": not errors, "week": week, "written": ok, "failed": len(errors),
                              APPLIED_PLAN_STATE_KEY: applied}
    if errors:
        result["errors"] = errors
    return json.dumps(result)


apply_training_plan_tool = FunctionTool(apply_training_plan)
