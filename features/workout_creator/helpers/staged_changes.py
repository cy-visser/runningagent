"""Staged workout / note changes: schema, resolution against TrainingPeaks and confirmation tables.

The coach never writes to TrainingPeaks directly. `stage_workout_changes` resolves each proposed
change (create or update, which workout it replaces) against ONE fetch of the planned calendar and
stores the set in session state; the web app shows it with an "Update TrainingPeaks" button.
`apply_staged_changes` writes the set in code, and the confirmation is rendered here, without an LLM.
"""

from datetime import date
from typing import Any, Optional

from ....shared.athlete_settings import sport_family, sport_thresholds
from ....shared.dates import iso_date, parse_date
from ....shared.units import as_float
from ....shared.workout_status import is_workout_completed
from .workout_builder import (
    builder_summary,
    builder_totals,
    coach_structure_from,
    has_builder,
    needs_builder,
    parse_coach_structure,
)

# Persisted session state (read by apply_staged_changes and forwarded to the web card).
STAGED_CHANGES_STATE_KEY = "staged_workout_changes"
# Set when a staged set is applied; the web marks that card as applied.
APPLIED_CHANGES_STATE_KEY = "applied_workout_changes"

KIND_WORKOUT = "workout"
KIND_NOTE = "note"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"

# What a Run/Bike change needs before it can be staged (internal marker, removed by finalize_builders).
BUILDER_COACH = "coach"      # the coach sent a structure: convert it exactly
BUILDER_MISSING = "missing"  # new workout without a structure: back to the coach
BUILDER_CHECK = "check"      # distance/duration changed without a structure: fetch the current builder

_NUMERIC_FIELDS = ("duration_minutes", "distance_km", "tss_planned")
_TOTAL_FIELDS = ("distance_km", "duration_minutes")
# Card detail line when a workout has no builder: the description, cut to this many characters.
DESCRIPTION_SUMMARY_CHARS = 140
DISTANCE_TOL_KM = 0.05
DURATION_TOL_MIN = 1.0
# Coach totals further than this from the builder totals are reported back (the builder wins).
TOTALS_NOTE_REL = 0.05
# Beyond this the builder and the coach disagree on the session: it goes back to the coach.
TOTALS_BLOCK_REL = 0.10


_WHOLE_FIELDS = ("duration_minutes", "tss_planned")


def _number(value: Any, field: Optional[str] = None) -> Optional[float]:
    """Whole numbers for duration and TSS (`field` in _WHOLE_FIELDS), one decimal otherwise (distance)."""
    try:
        if value is None or value == "":
            return None
        return round(float(value)) if field in _WHOLE_FIELDS else round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _totals_changed(change: dict, planned_km: Any, planned_hours: Any) -> bool:
    """True when the change sets a distance (not for bike: builders are timed) or duration that differs
    from the planned workout's."""
    distance = change.get("distance_km")
    if distance is not None and sport_family(change.get("sport")) != "bike":
        old = as_float(planned_km)
        if old is None or abs(distance - old) > DISTANCE_TOL_KM:
            return True
    duration = change.get("duration_minutes")
    if duration is not None:
        old = as_float(planned_hours)
        if old is None or abs(duration - old * 60.0) > DURATION_TOL_MIN:
            return True
    return False


def _mark_update_builder(change: dict, existing: Optional[dict]) -> None:
    """An update without a structure keeps the builder unless its distance/duration changes."""
    if change.get("builder") != BUILDER_MISSING:
        return
    no_totals = change.get("duration_minutes") is None and (
        change.get("distance_km") is None or sport_family(change.get("sport")) == "bike")
    if no_totals or (existing is not None and not _totals_changed(
        change, existing.get("distance_planned_km"), existing.get("duration_planned")
    )):
        change.pop("builder")  # move, rename or description edit: TrainingPeaks keeps the builder
    else:
        change["builder"] = BUILDER_CHECK


def _same_sport_planned(workouts: list[dict], day: str, sport: str) -> list[dict]:
    """Planned (not completed) workouts of `sport` on ISO date `day`."""
    sport_lower = sport.strip().lower()
    return [
        w for w in workouts
        if iso_date(parse_date(w.get("date") or w.get("start_time"))) == day
        and not is_workout_completed(w)
        and (w.get("sport") or "").strip().lower() == sport_lower
    ]


def staged_dates(raw_changes: list[dict]) -> list[date]:
    """Parsed dates of the raw changes (unparseable dates are skipped)."""
    return [d for d in (parse_date(str(c.get("date_str") or c.get("date") or "")) for c in raw_changes) if d]


def description_summary(text: Any) -> Optional[str]:
    """First non-empty line of a workout description, cut to DESCRIPTION_SUMMARY_CHARS (card detail line)."""
    line = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")
    if not line:
        return None
    return line if len(line) <= DESCRIPTION_SUMMARY_CHARS else line[: DESCRIPTION_SUMMARY_CHARS - 1].rstrip() + "…"


def existing_from_detail(detail: Optional[dict]) -> Optional[dict]:
    """A `tp_get_workout` payload in the `tp_get_workouts` list shape (planned values top level)."""
    if not detail:
        return None
    metrics = detail.get("metrics") or {}
    out = dict(detail)
    for key in ("distance_planned_km", "duration_planned", "tss_planned"):
        if out.get(key) is None and metrics.get(key) is not None:
            out[key] = metrics[key]
    return out


def replaces_snapshot(existing: Optional[dict]) -> Optional[dict]:
    """The planned values of the workout an update replaces (Current column of the web card), or None."""
    if not existing:
        return None
    hours = as_float(existing.get("duration_planned"))
    day = parse_date(existing.get("date") or existing.get("start_time"))
    snapshot = {
        "title": existing.get("title"),
        "date": iso_date(day) if day else None,
        "sport": existing.get("sport"),
        "distance_km": _number(existing.get("distance_planned_km")),
        "duration_minutes": _number(hours * 60.0, "duration_minutes") if hours else None,
        "tss_planned": _number(existing.get("tss_planned"), "tss_planned"),
    }
    summary = description_summary(existing.get("description"))
    if summary:
        snapshot["description_summary"] = summary
    return snapshot


def _inherit_unchanged(change: dict) -> None:
    """An update shows the session it keeps: the title and planned totals the coach did not set come
    from the current workout. They are listed in `inherited` and never written (TrainingPeaks keeps them)."""
    snapshot = change.get("replaces")
    if not snapshot:
        return
    inherited = []
    if not change.get("title") and snapshot.get("title"):
        change["title"] = snapshot["title"]
        inherited.append("title")
    for field in _NUMERIC_FIELDS:
        if change.get(field) is None and snapshot.get(field) is not None:
            change[field] = snapshot[field]
            inherited.append(field)
    if inherited:
        change["inherited"] = inherited
    if not change.get("description") and snapshot.get("description_summary"):
        change["description_summary"] = snapshot["description_summary"]


def _item_day(item: dict) -> Optional[str]:
    day = parse_date(item.get("date") or item.get("start_time"))
    return iso_date(day) if day else None


def _title_matches(items: list[dict], title: str) -> list[dict]:
    """Items whose title contains `title` (case-insensitive); all items when none does."""
    needle = title.lower()
    narrowed = [i for i in items if needle and needle in str(i.get("title") or "").lower()]
    return narrowed or items


def _is_completed(target: dict, listed: Optional[dict]) -> bool:
    """Calendar entry first, then the `tp_get_workout` flag, then its recorded actuals."""
    if listed:
        return is_workout_completed(listed)
    if "completed" in target:
        return bool(target["completed"])
    return is_workout_completed(target) or is_workout_completed(target.get("metrics") or {})


def _delete_note(day: Optional[str], title: str, notes: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """(staged note delete, problem): the single note on `day` (narrowed by title)."""
    matches = _title_matches([n for n in notes if _item_day(n) == day], title)
    if not day or not matches:
        return None, {"reason": "note_not_found", "date_str": day, "title": title}
    if len(matches) > 1:
        return None, {"reason": "ambiguous_note", "date_str": day, "title": title,
                      "candidates": [{"title": n.get("title")} for n in matches]}
    note = matches[0]
    return {"kind": KIND_NOTE, "action": ACTION_DELETE, "note_id": str(note.get("id") or ""), "date": day,
            "title": note.get("title") or "Note", "description_summary": description_summary(note.get("description"))}, None


def _delete_workout(
    raw: dict, day: Optional[str], title: str, workouts: list[dict], by_id: dict, details_by_id: dict
) -> tuple[Optional[dict], Optional[dict]]:
    """(staged workout delete, problem): the workout by id, else the single planned one on `day`
    (optionally of `sport`, narrowed by title). Completed workouts are never deleted."""
    workout_id = str(raw.get("workout_id") or "").strip()
    sport = str(raw.get("sport") or "").strip().lower()
    if workout_id:
        detail = existing_from_detail(details_by_id.get(workout_id))
        target = {**(by_id.get(workout_id) or {}), **{k: v for k, v in (detail or {}).items() if v is not None}}
        if not target:
            return None, {"reason": "workout_not_found", "workout_id": workout_id, "title": title}
        target.setdefault("id", workout_id)
    else:
        on_day = [w for w in workouts if _item_day(w) == day
                  and (not sport or str(w.get("sport") or "").strip().lower() == sport)]
        planned = _title_matches([w for w in on_day if not is_workout_completed(w)], title)
        if not planned:
            reason = "cannot_delete_completed" if on_day else "workout_not_found"
            return None, {"reason": reason, "date_str": day, "sport": raw.get("sport"), "title": title}
        if len(planned) > 1:
            return None, {"reason": "needs_workout_id", "date_str": day, "sport": raw.get("sport"),
                          "title": title or "Planned workout",
                          "candidates": [{"workout_id": str(w.get("id") or ""), "title": w.get("title"),
                                          "sport": w.get("sport")} for w in planned]}
        target = planned[0]
    if _is_completed(target, by_id.get(str(target["id"]))):
        return None, {"reason": "cannot_delete_completed", "workout_id": str(target["id"]), "title": target.get("title")}
    snapshot = replaces_snapshot(target) or {}
    return {"kind": KIND_WORKOUT, "action": ACTION_DELETE, "workout_id": str(target["id"]),
            "date": snapshot.get("date") or day or "", "sport": target.get("sport"),
            "title": target.get("title") or "Planned workout", "replaces": snapshot}, None


def resolve_changes(
    raw_changes: list[dict],
    workouts: list[dict],
    details_by_id: Optional[dict[str, dict]] = None,
    notes: Optional[list[dict]] = None,
) -> tuple[list[dict], list[dict]]:
    """Resolves raw coach changes against the planned calendar.

    Upsert rules per workout change: an explicit `workout_id` updates that workout (found in the
    fetched range or in `details_by_id`, the `tp_get_workout` payloads of the explicit ids, so a
    move to another date still knows the session; an id found in neither is not staged);
    `create=True` always creates; otherwise the single planned workout of the same sport on that
    date is updated, none -> create, several -> ambiguous (returned with candidates, not staged).
    Updates inherit the title and planned totals the coach did not change. Notes are always
    created. `delete=True` removes one planned workout (by id, or the single match on the date) or
    one calendar note (`notes`: the notes on the staged dates). Returns (staged changes, problems).
    """
    details_by_id = details_by_id or {}
    by_id = {str(w.get("id")): w for w in workouts if w.get("id") is not None}
    staged: list[dict] = []
    problems: list[dict] = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            problems.append({"reason": "invalid", "change": raw})
            continue
        raw_date = str(raw.get("date_str") or raw.get("date") or "")
        day = parse_date(raw_date)
        title = str(raw.get("title") or "").strip()
        kind = KIND_NOTE if str(raw.get("kind") or "").strip().lower() == KIND_NOTE else KIND_WORKOUT
        if raw.get("delete"):
            day_str = iso_date(day) if day else None
            change, problem = (_delete_note(day_str, title, notes or []) if kind == KIND_NOTE
                               else _delete_workout(raw, day_str, title, workouts, by_id, details_by_id))
            staged.extend([change] if change else [])
            problems.extend([problem] if problem else [])
            continue
        if not day:
            problems.append({"reason": "invalid_date", "date_str": raw_date, "title": title})
            continue
        # Keep a time of day when one was given (TrainingPeaks accepts YYYY-MM-DDTHH:MM:SS).
        date_value = raw_date if len(raw_date) > 10 and "T" in raw_date else iso_date(day)
        change: dict[str, Any] = {"kind": kind, "action": ACTION_CREATE, "date": date_value, "title": title}
        if raw.get("description"):
            change["description"] = str(raw["description"])

        if kind == KIND_NOTE:
            change["title"] = title or "Note"
            staged.append(change)
            continue

        sport = str(raw.get("sport") or "Run").strip() or "Run"
        change.update({"sport": sport, "workout_id": None})
        for field in _NUMERIC_FIELDS:
            change[field] = _number(raw.get(field), field)
        if raw.get("structure") not in (None, "", {}):
            change["structure"] = raw["structure"]
            change["builder"] = BUILDER_COACH
        elif needs_builder(sport):
            change["builder"] = BUILDER_MISSING

        workout_id = str(raw.get("workout_id") or "").strip()
        if workout_id:
            existing = by_id.get(workout_id)
            detail = existing_from_detail(details_by_id.get(workout_id))
            if detail:  # richer (description, builder) and found whatever its date
                existing = {**(existing or {}), **{k: v for k, v in detail.items() if v is not None}}
            if existing is None:  # never stage a blind update over a workout we could not read
                problems.append({"reason": "workout_not_found", "workout_id": workout_id,
                                 "date_str": iso_date(day), "sport": sport, "title": title})
                continue
            change.update({"action": ACTION_UPDATE, "workout_id": workout_id,
                           "replaces_title": existing.get("title"),
                           "replaces": replaces_snapshot(existing)})
            _mark_update_builder(change, existing)
        elif not raw.get("create"):
            candidates = _same_sport_planned(workouts, iso_date(day), sport)
            if len(candidates) > 1:
                problems.append({
                    "reason": "needs_workout_id", "date_str": iso_date(day), "sport": sport,
                    "title": title or f"Planned {sport}",
                    "candidates": [{"workout_id": str(w.get("id") or ""), "title": w.get("title")} for w in candidates],
                })
                continue
            if candidates:
                change.update({"action": ACTION_UPDATE, "workout_id": str(candidates[0].get("id") or ""),
                               "replaces_title": candidates[0].get("title"),
                               "replaces": replaces_snapshot(candidates[0])})
                _mark_update_builder(change, candidates[0])
        # The builder rules above see only the coach's values; the card then shows the session it keeps.
        _inherit_unchanged(change)
        change["title"] = change["title"] or f"Planned {sport}"
        if change.get("description"):
            change["description_summary"] = description_summary(change["description"])
        staged.append(change)
    staged.sort(key=lambda c: (c["date"], c["kind"]))
    return staged, problems


def is_edit_only(changes: list[dict]) -> bool:
    """True when every change only moves, renames or re-describes an existing workout: same builder and
    no planned total set by the coach (the runner asked for it; nothing to explain)."""
    def edit(c: dict) -> bool:
        inherited = set(c.get("inherited") or ())
        return (
            c.get("kind") == KIND_WORKOUT and c.get("action") == ACTION_UPDATE and not c.get("structured_workout")
            and all(c.get(f) is None or f in inherited for f in _NUMERIC_FIELDS)
        )
    return bool(changes) and all(edit(c) for c in changes)


# ------------------------------------------------------------------------------
# Workout builder (exact, never scaled)
# ------------------------------------------------------------------------------

def _needs_structure(change: dict, why: str, current: Optional[dict] = None) -> dict:
    return {
        "reason": "needs_structure", "why": why, "date_str": change["date"][:10], "sport": change.get("sport"),
        "title": change.get("title"), "workout_id": change.get("workout_id"), "current_structure": current,
    }


def _totals_mismatch(change: dict, totals: dict) -> Optional[str]:
    """Why the builder does not match the coach's own distance / duration (> TOTALS_BLOCK_REL), else None."""
    inherited = set(change.get("inherited") or ())
    units = {"distance_km": "km", "duration_minutes": "min"}
    for field in _TOTAL_FIELDS:
        builder, coach = totals.get(field), None if field in inherited else change.get(field)
        if builder is not None and coach and abs(builder - coach) > TOTALS_BLOCK_REL * max(builder, coach):
            return (f"the steps add up to {round(builder, 1):g} {units[field]} but you stated {coach:g} {units[field]}: "
                    "fix the steps (or the stated total and title) and stage again")
    return None


def _apply_builder(change: dict, native: dict, thr: dict, notes: list[dict]) -> None:
    """Attaches the native builder; distance / duration / TSS follow it (the coach's numbers are reported
    back when they differ by more than TOTALS_NOTE_REL; values inherited from the current workout are not
    the coach's and are simply replaced)."""
    totals = builder_totals(native, thr)
    inherited = set(change.get("inherited") or ())
    for field in (*_TOTAL_FIELDS, "tss_planned"):
        value = totals[field]
        if value is None:
            continue
        coach = None if field in inherited else change.get(field)
        if field in _TOTAL_FIELDS and coach is not None and abs(value - coach) > TOTALS_NOTE_REL * max(value, coach):
            notes.append({"date": change["date"][:10], "title": change.get("title"), "field": field,
                          "coach": coach, "builder": value})
        change[field] = value
        inherited.discard(field)
    _set_inherited(change, inherited)
    change["structured_workout"] = native
    change["structure_summary"] = builder_summary(native, thr)


def _set_inherited(change: dict, inherited: set[str]) -> None:
    kept = [f for f in ("title", *_NUMERIC_FIELDS) if f in inherited]
    if kept:
        change["inherited"] = kept
    else:
        change.pop("inherited", None)


def _show_current_builder(change: dict, detail: Optional[dict], thr: dict) -> None:
    """Card detail of an update: the current workout's builder summary (Current column) and, when the
    change keeps that builder, on the proposed side too."""
    current = (detail or {}).get("structured_workout")
    if not change.get("replaces") or not has_builder(current):
        return
    summary = builder_summary(current, thr)
    if not summary:
        return
    change["replaces"]["structure_summary"] = summary
    if not change.get("structured_workout"):
        change.setdefault("structure_summary", summary)


def finalize_builders(
    staged: list[dict], settings_raw: Any, details_by_id: dict[str, dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Applies the workout-builder rules to resolved changes.

    - A coach `structure` becomes the exact native builder; distance / duration / TSS follow it.
    - A Run/Bike create without a structure goes back to the coach (`missing`).
    - A Run/Bike update whose distance/duration changes without a structure goes back to the coach with
      the builder that is in TrainingPeaks now (`current_structure`, exact), so it edits only what changes.
    - Moves, renames and description edits keep the existing builder.
    Updates whose current workout was read show its builder summary on the card.
    Returns (changes ready to stage, needs_structure problems, totals notes).
    """
    ready: list[dict] = []
    needs: list[dict] = []
    notes: list[dict] = []
    for change in staged:
        if change.get("action") == ACTION_DELETE:
            ready.append(change)
            continue
        marker = change.pop("builder", None)
        raw_structure = change.pop("structure", None)
        thr = sport_thresholds(settings_raw, change.get("sport"))
        if change.get("workout_id"):
            _show_current_builder(change, details_by_id.get(str(change["workout_id"])), thr)
        if marker == BUILDER_COACH:
            native, error = parse_coach_structure(raw_structure, change.get("sport"), thr)
            if error:
                needs.append(_needs_structure(change, f"invalid: {error}"))
                continue
            mismatch = _totals_mismatch(change, builder_totals(native, thr))
            if mismatch:
                needs.append(_needs_structure(change, mismatch))
                continue
            _apply_builder(change, native, thr, notes)
        elif marker == BUILDER_MISSING:
            needs.append(_needs_structure(change, "missing"))
            continue
        elif marker == BUILDER_CHECK:
            detail = details_by_id.get(str(change.get("workout_id")))
            if detail is None:
                needs.append(_needs_structure(change, "distance/duration changed (the current builder could not be read)"))
                continue
            metrics = detail.get("metrics") or {}
            if not _totals_changed(change, metrics.get("distance_planned_km"), metrics.get("duration_planned")):
                ready.append(change)  # same totals after all: TrainingPeaks keeps the builder
                continue
            current = detail.get("structured_workout")
            if has_builder(current):
                needs.append(_needs_structure(change, "distance/duration changed", coach_structure_from(current, thr)))
            else:
                needs.append(_needs_structure(change, "missing"))
            continue
        ready.append(change)
    return ready, needs, notes


# ------------------------------------------------------------------------------
# Coded confirmation text
# ------------------------------------------------------------------------------

def _display_date(value: str) -> str:
    day = parse_date(value)
    return day.strftime("%a %d %b") if day else value


def _fmt(value: Any, unit: str = "", field: Optional[str] = None) -> str:
    num = _number(value, field)
    if num is None:
        return "–"
    text = f"{num:g}"
    return f"{text} {unit}".strip()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _cell(text: Any) -> str:
    return str(text or "").replace("|", "/").replace("\n", " ").strip() or "–"


def change_label(change: dict) -> str:
    """'Created', 'Updated', 'Moved' (an update whose current workout is on another date) or 'Deleted'."""
    if change.get("action") == ACTION_DELETE:
        return "Deleted"
    if change.get("action") != ACTION_UPDATE:
        return "Created"
    before = (change.get("replaces") or {}).get("date")
    return "Moved" if before and before != str(change.get("date") or "")[:10] else "Updated"


def workout_metrics(values: dict, show_sport: bool) -> str:
    """'10 km · 61 min · TSS 68' (sport first for non-run sessions); '' when nothing is known."""
    parts = [str(values["sport"])] if show_sport and values.get("sport") else []
    if _number(values.get("distance_km")):
        parts.append(_fmt(values["distance_km"], "km"))
    if _number(values.get("duration_minutes")):
        parts.append(_fmt(values["duration_minutes"], "min", "duration_minutes"))
    if _number(values.get("tss_planned")) is not None:
        parts.append(f"TSS {_fmt(values['tss_planned'], field='tss_planned')}")
    return " · ".join(parts)


def _workout_cell(title: Any, values: dict) -> str:
    sport = str(values.get("sport") or "")
    metrics = workout_metrics(values, show_sport=sport.lower() != "run")
    return f"**{_cell(title)}**" + (f" · {metrics}" if metrics else "")


def _before_cell(change: dict) -> str:
    if change.get("action") not in (ACTION_UPDATE, ACTION_DELETE):
        return "–"
    before = change.get("replaces") or {}
    cell = _workout_cell(before.get("title") or change.get("replaces_title") or "Existing workout", before)
    if change_label(change) == "Moved":
        cell += f" ({_display_date(before['date'])})"
    return cell


def confirmation_text(results: list[dict]) -> str:
    """Markdown confirmation of an applied staged set: summary line, applied table, failures."""
    applied = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    workouts = [r for r in applied if r.get("kind") != KIND_NOTE]
    notes = [r for r in applied if r.get("kind") == KIND_NOTE]
    deleted = sum(1 for r in workouts if r.get("action") == ACTION_DELETE)

    if not applied:
        lines = ["⚠️ **TrainingPeaks was not updated.**"]
    else:
        counts = [c for c in (
            workouts and _plural(len(workouts), "workout") + (f" ({deleted} deleted)" if deleted else ""),
            notes and _plural(len(notes), "note"),
        ) if c]
        lines = [f"✅ **TrainingPeaks updated:** {' and '.join(counts)}."]

    if workouts:
        lines += ["", "| Change | Date | Before | After |", "|---|---|---|---|"]
        for r in workouts:
            after = "–" if r.get("action") == ACTION_DELETE else _workout_cell(r.get("title"), r)
            lines.append(f"| {change_label(r)} | {_display_date(r['date'])} | {_before_cell(r)} | {after} |")
    for r in notes:
        verb = "🗑️ Note removed" if r.get("action") == ACTION_DELETE else "📝 Note added"
        lines += ["", f"{verb}: {_display_date(r['date'])} · {_cell(r.get('title'))}"]
    if failed:
        lines += ["", "⚠️ **Not saved:**"]
        lines += [
            f"- {_display_date(r['date'])} {_cell(r.get('sport') or 'Note')} \"{_cell(r.get('title'))}\": "
            f"{_cell(r.get('error') or 'unknown error')}"
            for r in failed
        ]
    return "\n".join(lines)
