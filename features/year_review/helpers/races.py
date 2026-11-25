"""Structured multi-signal main-race detection and profile-only PR matching for the 12-month review."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from ....shared.dates import iso_date, parse_date
from ....shared.goal_distance import DISTANCE_PROFILES, resolve_goal_distance
from ....shared.goal_plan import KIND_NORTH_STAR, KIND_SUB_GOAL, goal_list, race_day
from ....shared.race_equivalents import goal_target_s
from ....shared.race_events import (
    event_date_iso,
    event_distance_km,
    event_priority,
    has_race_tag,
    is_running_event,
)
from ....shared.race_time import parse_race_time
from ....shared.sports import RUN_SPORTS
from ....shared.units import as_float

MAX_RACE_DETAIL_FETCHES = 10

# Short label for chart pins keyed by canonical distance label.
_SHORT_LABELS = {
    "5K": "5K",
    "10K": "10K",
    "10 Mile": "10M",
    "Half Marathon": "HM",
    "Marathon": "Marathon",
}

# Standard race distances (km) -> (profile personal_records key, canonical label, km).
_STANDARD_DISTANCES_KM: list[tuple[str, str, float]] = [
    ("5k", "5K", 5.0),
    ("10k", "10K", 10.0),
    ("10_mile", "10 Mile", 16.0934),
    ("half_marathon", "Half Marathon", 21.0975),
    ("marathon", "Marathon", 42.195),
]
_LABEL_TO_PR_KEY = {label: key for key, label, _ in _STANDARD_DISTANCES_KM}


def _is_run_workout(workout: dict[str, Any]) -> bool:
    sport = str(workout.get("sport") or "").strip().lower()
    return sport in RUN_SPORTS or sport == "race"


def _distance_label_for_km(distance_km: Optional[float], title: str = "") -> Optional[str]:
    if distance_km and distance_km > 0:
        for _, label, std_km in _STANDARD_DISTANCES_KM:
            if abs(distance_km - std_km) / std_km <= 0.08:
                return label
    return resolve_goal_distance(title)


def _short_label(distance_km: Optional[float], title: str = "") -> str:
    label = _distance_label_for_km(distance_km, title)
    if label and label in _SHORT_LABELS:
        return _SHORT_LABELS[label]
    if distance_km and distance_km > 0:
        return f"{distance_km:.0f}K" if distance_km >= 3 else f"{distance_km:.1f}K"
    return "Race"


def _workout_duration_s(workout: dict[str, Any], record: Optional[dict[str, Any]] = None) -> Optional[float]:
    if record and as_float(record.get("duration_s")):
        return as_float(record.get("duration_s"))
    hours = as_float(workout.get("duration_actual"))
    return round(hours * 3600.0, 1) if hours and hours > 0 else None


def _workout_distance_km(workout: dict[str, Any], record: Optional[dict[str, Any]] = None) -> Optional[float]:
    if record and as_float(record.get("distance_km")):
        return as_float(record.get("distance_km"))
    km = as_float(workout.get("distance_actual_km"))
    if km and km > 0:
        return km
    return None


def _pick_workout_for_date(
    target_iso: str,
    workouts_by_date: dict[str, list[dict[str, Any]]],
    *,
    preferred_ids: Optional[set[str]] = None,
    target_km: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    candidates = [w for w in workouts_by_date.get(target_iso, []) if _is_run_workout(w)]
    if not candidates:
        return None
    if preferred_ids:
        for w in candidates:
            if str(w.get("id") or "") in preferred_ids:
                return w
    if target_km and target_km > 0:
        return min(
            candidates,
            key=lambda w: abs((as_float(w.get("distance_actual_km")) or 0.0) - target_km),
        )
    # Prefer explicitly marked Race / race-tagged runs, then longest completed run on race day.
    return max(
        candidates,
        key=lambda w: (
            1 if str(w.get("sport") or "").lower() == "race" or has_race_tag(w.get("tags")) else 0,
            as_float(w.get("distance_actual_km")) or 0.0,
            as_float(w.get("duration_actual")) or 0.0,
        ),
    )


def _dates_within_one_day(a_iso: str, b_iso: Optional[str]) -> bool:
    da, db = parse_date(a_iso), parse_date(b_iso)
    return bool(da and db and abs((da - db).days) <= 1)


def _profile_pr_time_s(entry: dict[str, Any]) -> Optional[float]:
    secs = as_float(entry.get("time_s"))
    if secs and secs > 0:
        return secs
    if entry.get("time"):
        try:
            _, parsed_s = parse_race_time(entry["time"])
            return float(parsed_s)
        except ValueError:
            return None
    return None


def _is_race_pr(
    *,
    race_date: str,
    distance_label: Optional[str],
    duration_s: Optional[float],
    profile: dict[str, Any],
) -> bool:
    """Distance-matched PR check sourced strictly from `profile.personal_records`."""
    prs = profile.get("personal_records")
    if not isinstance(prs, dict) or not distance_label:
        return False
    pr_key = _LABEL_TO_PR_KEY.get(distance_label)
    if not pr_key:
        return False
    entry = prs.get(pr_key)
    if not isinstance(entry, dict):
        return False
    if entry.get("date") and _dates_within_one_day(race_date, str(entry["date"])):
        return True
    pr_secs = _profile_pr_time_s(entry)
    if pr_secs is not None and duration_s is not None and duration_s > 0:
        return duration_s <= pr_secs
    return False


def _pmc_by_date(daily_pmc: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in daily_pmc or []:
        d = str(row.get("date") or "")[:10]
        ctl = as_float(row.get("ctl"))
        if d and ctl is not None:
            out[d] = round(ctl, 1)
    return out


def _ctl_on_or_before(day_iso: str, pmc_map: dict[str, float]) -> Optional[float]:
    d = parse_date(day_iso)
    if not d:
        return None
    for offset in range(7):
        key = iso_date(d - timedelta(days=offset))
        if key in pmc_map:
            return pmc_map[key]
    return None


def detect_main_races(
    *,
    profile: dict[str, Any],
    workouts: list[dict[str, Any]],
    records: list[dict[str, Any]],
    events: list[dict[str, Any]],
    daily_pmc: list[dict[str, Any]],
    start: date,
    today: date,
    lthr: Optional[float] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Detects and merges main races in `[start, today]` from structured TP & Profile signals only.

    Signals (zero title/distance guessing):
    1. TrainingPeaks Calendar Events (`tp_get_events`)
    2. Profile Goal Plan (`sub_goals` / `north_star` / `single` goal)
    3. Explicitly marked TP workouts (`sport == "Race"` or `tags` containing `race`)

    Returns `(races, unlogged_workout_ids)` where `unlogged_workout_ids` (at most
    `MAX_RACE_DETAIL_FETCHES`) are races without an analyzed `training_log` record
    that can be cheaply enriched with `tp_get_workout`.
    """
    start_iso, end_iso = iso_date(start), iso_date(today)
    records_by_id = {str(r.get("workout_id") or ""): r for r in (records or []) if r.get("workout_id")}
    workouts_by_id = {str(w.get("id") or ""): w for w in (workouts or []) if w.get("id") is not None}
    workouts_by_date: dict[str, list[dict[str, Any]]] = {}
    for w in workouts or []:
        d = str(w.get("date") or "")[:10]
        if start_iso <= d <= end_iso:
            workouts_by_date.setdefault(d, []).append(w)

    pmc_map = _pmc_by_date(daily_pmc)

    # Keyed by (date, workout_id or fallback slug) so multiple signals on the same race merge cleanly.
    merged: dict[str, dict[str, Any]] = {}
    by_date_key: dict[str, str] = {}

    def _upsert(
        *,
        race_date: str,
        name: str,
        workout: Optional[dict[str, Any]] = None,
        priority: Optional[str] = None,
        badge: Optional[str] = None,
        source: str = "workout",
        goal_text: Optional[str] = None,
        goal_target_sec: Optional[float] = None,
        result_duration_s: Optional[float] = None,
        distance_km_hint: Optional[float] = None,
        note: Optional[str] = None,
    ) -> None:
        wid = str(workout["id"]) if workout and workout.get("id") is not None else None
        key = f"w:{wid}" if wid else by_date_key.get(race_date) or f"d:{race_date}:{name.lower()[:24]}"
        if wid and race_date in by_date_key and by_date_key[race_date] != key:
            prev_key = by_date_key[race_date]
            prev = merged.get(prev_key)
            if prev and (prev.get("workout_id") is None or prev.get("workout_id") == wid):
                merged[key] = merged.pop(prev_key)
        by_date_key[race_date] = key

        rec = records_by_id.get(wid) if wid else None
        existing = merged.get(key) or {
            "date": race_date,
            "workout_id": wid,
            "name": name,
            "priority": None,
            "badge": "Race",
            "sources": [],
            "distance_km": None,
            "duration_s": None,
            "pace_s": None,
            "avg_hr": None,
            "pct_lthr": None,
            "pa_hr": None,
            "ctl": _ctl_on_or_before(race_date, pmc_map),
            "is_pr": False,
            "goal_text": None,
            "goal_gap_s": None,
            "note": None,
            "has_log_record": bool(rec),
        }

        if source not in existing["sources"]:
            existing["sources"].append(source)
        # Prefer event / sub-goal names over generic workout titles.
        if source in ("sub_goal", "event") and name:
            existing["name"] = name
        elif not existing.get("name") and name:
            existing["name"] = name

        if wid and not existing.get("workout_id"):
            existing["workout_id"] = wid
        if rec:
            existing["has_log_record"] = True

        # Badge precedence: Sub-Goal > A/B/C Event Priority > Race
        if badge == "Sub-Goal":
            existing["badge"] = "Sub-Goal"
        elif priority in ("A", "B", "C") and existing["badge"] != "Sub-Goal":
            existing["priority"] = priority
            existing["badge"] = f"{priority} Race"
        elif priority in ("A", "B", "C"):
            existing["priority"] = priority

        dist = _workout_distance_km(workout or {}, rec) or distance_km_hint or existing.get("distance_km")
        dur = _workout_duration_s(workout or {}, rec) or result_duration_s or existing.get("duration_s")
        if dist and dist > 0:
            existing["distance_km"] = round(float(dist), 2)
        if dur and dur > 0:
            existing["duration_s"] = round(float(dur))
        if existing["distance_km"] and existing["duration_s"]:
            existing["pace_s"] = round(existing["duration_s"] / existing["distance_km"], 1)

        if rec:
            avg_hr = as_float(rec.get("avg_hr"))
            if avg_hr:
                existing["avg_hr"] = round(avg_hr)
                if lthr and lthr > 0:
                    existing["pct_lthr"] = round((avg_hr / lthr) * 100)
                elif as_float(rec.get("pct_lthr")):
                    existing["pct_lthr"] = round(float(rec["pct_lthr"]) * 100)
            pa_hr = as_float(rec.get("session_decoupling"))
            if pa_hr is None:
                pa_hr = as_float(rec.get("pa_hr"))
            if pa_hr is not None:
                existing["pa_hr"] = round(pa_hr, 1)

        if goal_text:
            existing["goal_text"] = goal_text
        if goal_target_sec and existing.get("duration_s"):
            existing["goal_gap_s"] = round(existing["duration_s"] - goal_target_sec)
        if note and not existing.get("note"):
            existing["note"] = note

        merged[key] = existing

    # Signal 1: TrainingPeaks Calendar Events
    for ev in events or []:
        if not isinstance(ev, dict) or not is_running_event(ev):
            continue
        ev_iso = event_date_iso(ev)
        if not ev_iso or not (start_iso <= ev_iso <= end_iso):
            continue
        ev_name = str(ev.get("name") or "").strip() or "Race Event"
        prio = event_priority(ev)
        ev_dist = event_distance_km(ev)
        linked_ids = {str(wid) for wid in (ev.get("workouts") or []) if wid is not None}
        matched_w = next((workouts_by_id[i] for i in linked_ids if i in workouts_by_id), None)
        if matched_w is None:
            matched_w = _pick_workout_for_date(ev_iso, workouts_by_date, preferred_ids=linked_ids, target_km=ev_dist)
        if matched_w is None and not ev.get("results"):
            continue  # Skip unrun/future events without a completed workout
        # TP populates empty placeholder results rows [{"resultType": ..., "place": null}]; require an actual run or result.
        has_real_result = any(
            isinstance(r, dict) and r.get("place") is not None
            for r in (ev.get("results") or [])
        )
        if matched_w is None and not has_real_result:
            continue
        _upsert(
            race_date=ev_iso,
            name=ev_name,
            workout=matched_w,
            priority=prio,
            source="event",
            distance_km_hint=ev_dist,
        )

    # Signal 2: Profile Goal Plan Sub-Goals / Completed Goals in window
    for block in goal_list(profile):
        r_day = race_day(block)
        if not r_day:
            continue
        r_iso = iso_date(r_day)
        if not (start_iso <= r_iso <= end_iso):
            continue
        goal_text = str(block.get("training_goal") or "").strip()
        race_name = str(block.get("race_name") or goal_text or "Goal Race").strip()
        goal_label = resolve_goal_distance(goal_text)
        target_km = float(DISTANCE_PROFILES[goal_label]["km"]) if goal_label in DISTANCE_PROFILES else None
        result = block.get("result")
        result_wid = str(result.get("workout_id")) if isinstance(result, dict) and result.get("workout_id") else None
        result_s = as_float(result.get("time_s")) if isinstance(result, dict) else None
        matched_w = workouts_by_id.get(result_wid) if result_wid else None
        if matched_w is None:
            matched_w = _pick_workout_for_date(r_iso, workouts_by_date, target_km=target_km)
        if matched_w is None and not result_s:
            continue
        badge = "Sub-Goal" if block.get("kind") == KIND_SUB_GOAL else ("A Race" if block.get("kind") == KIND_NORTH_STAR else "Race")
        _upsert(
            race_date=r_iso,
            name=race_name,
            workout=matched_w,
            priority="A" if block.get("kind") == KIND_NORTH_STAR else None,
            badge=badge,
            source="sub_goal",
            goal_text=goal_text or None,
            goal_target_sec=goal_target_s(goal_text),
            result_duration_s=result_s,
            distance_km_hint=target_km,
        )

    # Signal 3: Explicitly marked TP race workouts (`sport == "Race"` or `tags` contains `race`)
    for w in workouts or []:
        d = str(w.get("date") or "")[:10]
        if not (start_iso <= d <= end_iso) or not _is_run_workout(w):
            continue
        sport_lower = str(w.get("sport") or "").strip().lower()
        if sport_lower != "race" and not has_race_tag(w.get("tags")):
            continue
        title = str(w.get("title") or "").strip()
        _upsert(
            race_date=d,
            name=title or "Race",
            workout=w,
            source="workout",
        )

    # Finalize labels, profile-only PR status, and sort reverse-chronologically (most recent first).
    races: list[dict[str, Any]] = []
    unlogged_ids: list[str] = []
    for item in merged.values():
        dist_label = _distance_label_for_km(item.get("distance_km"), item.get("name") or "")
        item["distance_label"] = dist_label
        item["short_label"] = _short_label(item.get("distance_km"), item.get("name") or "")
        item["is_pr"] = _is_race_pr(
            race_date=item["date"],
            distance_label=dist_label,
            duration_s=as_float(item.get("duration_s")),
            profile=profile,
        )
        races.append(item)

    races.sort(key=lambda r: (r["date"], r.get("distance_km") or 0.0), reverse=True)
    for r in races:
        if r.get("workout_id") and not r.get("has_log_record") and r.get("avg_hr") is None:
            unlogged_ids.append(str(r["workout_id"]))
            if len(unlogged_ids) >= MAX_RACE_DETAIL_FETCHES:
                break
    return races, unlogged_ids


def enrich_races_with_details(
    races: list[dict[str, Any]],
    details_by_id: dict[str, dict[str, Any]],
    lthr: Optional[float] = None,
) -> None:
    """Fills missing HR / IF / elevation / athlete note fields on races from lightweight `tp_get_workout` details."""
    for race in races:
        wid = str(race.get("workout_id") or "")
        detail = details_by_id.get(wid)
        if not isinstance(detail, dict):
            continue
        metrics = detail.get("metrics") or {}
        if race.get("avg_hr") is None:
            hr = as_float(detail.get("avg_hr")) or as_float(metrics.get("avg_hr")) or as_float(metrics.get("heart_rate_avg"))
            if hr and hr > 0:
                race["avg_hr"] = round(hr)
                if lthr and lthr > 0:
                    race["pct_lthr"] = round((hr / lthr) * 100)
        if race.get("duration_s") is None:
            hours = as_float(metrics.get("duration_actual"))
            if hours and hours > 0:
                race["duration_s"] = round(hours * 3600.0)
        if race.get("distance_km") is None:
            km = as_float(metrics.get("distance_actual_km"))
            if km and km > 0:
                race["distance_km"] = round(km, 2)
        if race.get("distance_km") and race.get("duration_s") and race.get("pace_s") is None:
            race["pace_s"] = round(race["duration_s"] / race["distance_km"], 1)
        if race.get("note") is None:
            comment = str(detail.get("new_comment") or "").strip()
            if comment:
                race["note"] = comment[:80]
