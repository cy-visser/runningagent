"""Compact plan context for the coach (~1-2k tokens for 24 weeks): goal, constraints, zones, recent training,
and the planned calendar of the window summarised per ISO week (no full workout dumps)."""

from datetime import date, timedelta
from typing import Any, Optional

from ....shared.calendar_notes import truncate_note
from ....shared.dates import iso_date, monday_of, parse_date
from ....shared.goal_plan import blocks, current_goal, north_star, race_day
from ....shared.long_run_facts import (
    LONG_RUN_HISTORY_WEEKS,
    VOLUME_HISTORY_WEEKS,
    format_history,
    format_volume_history_facts,
    format_weekly_km_history,
)
from ....shared.session_state import PLAN_CONTEXT_STATE_KEY
from ....shared.training_times import training_times_text
from ....shared.workout_status import is_workout_completed
from .pace_zones import zone_table_text
from .plan_diff import MANAGED_SPORTS, sport_name

TEMP_PLAN_WORKOUTS_KEY = "temp:plan_workouts"
HISTORY_WEEKS = VOLUME_HISTORY_WEEKS
FREQUENCY_WEEKS = 8
NOTE_CHARS = 60
_SPORT_SHORT = {"Run": "Run", "Bike": "Bike", "Strength": "Str"}


def _goal_lines(profile: dict, start: date, end: date) -> list[str]:
    goal = current_goal(profile, end)
    lines = []
    if goal.get("training_goal"):
        race = race_day(goal)
        weeks = f", {(race - monday_of(start)).days // 7} weeks after W1 starts" if race else ""
        lines.append(f"Goal: {goal['training_goal']} on {goal.get('timeline') or 'an unset date'}{weeks}")
    ns = north_star(profile)
    if ns and ns.get("timeline") != goal.get("timeline"):
        lines.append(f"North star: {ns['training_goal']} on {ns.get('timeline')}")
    races = [b for b in blocks(profile) if (d := race_day(b)) and start <= d <= end]
    if races:
        lines.append("Goal races in the window: " + " · ".join(f"{b['timeline']} {b['training_goal']}" for b in races))
    if str(profile.get("injuries") or "").strip():
        lines.append(f"Injuries: {profile['injuries']}")
    times = training_times_text(profile)
    lines.append(f"Training times: {times}" if times else
                 "Training times: not set (default: run first, strength after on a double day)")
    return lines


def _recent_lines(history_entries: list[dict], fitness: Optional[dict]) -> list[str]:
    km = format_weekly_km_history(history_entries) or "–"
    vol_facts = format_volume_history_facts(history_entries)
    vol_suffix = f" ({vol_facts})" if vol_facts else ""
    lines = [f"- Running km/week, last {len(history_entries)} weeks (oldest first): {km}{vol_suffix}"]
    longs = format_history(history_entries[-LONG_RUN_HISTORY_WEEKS:])
    if longs:
        lines.append(f"- Long runs, last {LONG_RUN_HISTORY_WEEKS} weeks: {longs}")
    if fitness:
        lines.append("- Today: " + " · ".join(f"{k.upper()} {round(v)}" for k, v in fitness.items() if v is not None))
    recent = history_entries[-FREQUENCY_WEEKS:]
    if recent:
        strength = sum(int(e.get("strength_count") or 0) for e in recent) / len(recent)
        bike = sum(int(e.get("bike_count") or 0) for e in recent) / len(recent)
        lines.append(f"- Last {len(recent)} weeks: strength {strength:.1f}/week · bike {bike:.1f}/week")
    return lines


def _session_text(w: dict, with_ids: bool) -> str:
    day = parse_date(w.get("date") or w.get("start_time"))
    sport = sport_name(w.get("sport"))
    km = w.get("distance_planned_km")
    text = f"{day.strftime('%a')} {_SPORT_SHORT.get(sport, sport)} '{w.get('title') or sport}'"
    if km:
        text += f" {float(km):g} km"
    elif w.get("duration_planned"):
        text += f" {round(float(w['duration_planned']) * 60)}'"
    if with_ids and w.get("id"):
        text += f" [{w['id']}]"
    return text


def _flush_empty_run(lines: list[str], run: list[tuple[int, date]]) -> None:
    if len(run) == 1:
        w_num, w_start = run[0]
        lines.append(f"W{w_num} {iso_date(w_start)}: nothing planned")
    elif len(run) >= 2:
        first_w, first_d = run[0]
        last_w, last_d = run[-1]
        lines.append(f"W{first_w}–W{last_w} ({iso_date(first_d)} → {iso_date(last_d)}): nothing planned")
    run.clear()


def _calendar_lines(
    workouts: list[dict], notes: list[dict], start: date, end: date, n_weeks: int, overhaul: bool
) -> list[str]:
    lines: list[str] = []
    empty_run: list[tuple[int, date]] = []
    monday = monday_of(start)
    for i in range(n_weeks):
        w_start, w_end = monday + timedelta(weeks=i), monday + timedelta(weeks=i, days=6)
        eff_start, eff_end = max(w_start, start), min(w_end, end)
        planned = sorted(
            (w for w in workouts if not is_workout_completed(w)
             and (d := parse_date(w.get("date") or w.get("start_time"))) and eff_start <= d <= eff_end),
            key=lambda w: str(w.get("start_time") or w.get("date")))
        if overhaul:
            body = " · ".join(_session_text(w, True) for w in planned) or "nothing planned"
        else:
            sports = [sport_name(w.get("sport")) for w in planned]
            run_km = sum(float(w.get("distance_planned_km") or 0) for w in planned if sport_name(w.get("sport")) == "Run")
            parts = [f"{sports.count(s)} {s.lower()}" + (f" {run_km:.0f} km" if s == "Run" and run_km else "")
                     for s in MANAGED_SPORTS if sports.count(s)]
            others = len(sports) - sum(sports.count(s) for s in MANAGED_SPORTS)
            parts += [f"{others} other"] if others else []
            body = ", ".join(parts) or "nothing planned"
        week_notes = [truncate_note(n.get("title") or "Note", NOTE_CHARS) for n in notes
                      if (d := parse_date(n.get("date"))) and eff_start <= d <= eff_end]
        partial = (
            f" (partial, {eff_start.strftime('%a')}–{eff_end.strftime('%a')})"
            if (eff_start > w_start or eff_end < w_end) else ""
        )
        if not planned and not week_notes and not partial:
            empty_run.append((i + 1, eff_start))
            continue
        _flush_empty_run(lines, empty_run)
        lines.append(
            f"W{i + 1} {iso_date(eff_start)}{partial}: {body}"
            + (f" | notes: {'; '.join(week_notes)}" if week_notes else "")
        )
    _flush_empty_run(lines, empty_run)
    return lines


def plan_context_text(
    profile: dict, start: date, end: date, mode: str, today: date, zones: dict,
    history_entries: Optional[list[dict]], workouts: Optional[list[dict]], notes: Optional[list[dict]],
    fitness: Optional[dict],
) -> str:
    del today
    w1_mon = monday_of(start)
    n_weeks = (monday_of(end) - w1_mon).days // 7 + 1
    if start > w1_mon:
        w1_end = min(end, w1_mon + timedelta(days=6))
        w1_desc = (
            f"W1 partial: {start.strftime('%a')} {iso_date(start)} → {w1_end.strftime('%a')} {iso_date(w1_end)}; "
            f"days before {iso_date(start)} are skipped — scale W1 volume proportionally"
        )
    else:
        w1_desc = f"W1 = week of {iso_date(w1_mon)}"
    head = (f"PLAN CONTEXT ({mode}): {iso_date(start)} → {iso_date(end)} · {n_weeks} weeks "
            f"({w1_desc}). Stage with stage_training_plan(plan={{\"start_date\": "
            f"\"{iso_date(start)}\", \"mode\": \"{mode}\", \"weeks\": [\"W1 | base | ...\"]}}, message=...).")
    sections = [head, "\n".join(_goal_lines(profile, start, end)),
                "ZONES (each code resolves to these; the app builds every session):\n" + zone_table_text(zones)]
    if history_entries is None:
        sections.append("RECENT TRAINING: unavailable (TrainingPeaks error).")
    else:
        sections.append("RECENT TRAINING (completed):\n" + "\n".join(_recent_lines(history_entries, fitness)))
    if workouts is None:
        sections.append("CALENDAR IN WINDOW: unavailable (TrainingPeaks error); staging reads it again.")
    else:
        label = "planned, per ISO week" + (", with [workout_id]" if mode == "overhaul" else "")
        sections.append(f"CALENDAR IN WINDOW ({label}):\n" + "\n".join(
            _calendar_lines(workouts, notes or [], start, end, n_weeks, mode == "overhaul")))
    return "\n\n".join(s for s in sections if s)


def latest_fitness(raw_daily: Any) -> Optional[dict]:
    """{'ctl', 'atl', 'tsb'} of the latest PMC day with a CTL, or None."""
    rows = [d for d in raw_daily or [] if isinstance(d, dict) and d.get("ctl") is not None]
    if not rows:
        return None
    last = rows[-1]
    return {"ctl": last.get("ctl"), "atl": last.get("atl"), "tsb": last.get("tsb")}
