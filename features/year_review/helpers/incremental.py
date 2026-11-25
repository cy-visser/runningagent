"""Calendar-year incremental delta planning, merge, and compact raw snapshot persistence."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ....shared.dates import iso_date, parse_date
from ....shared.units import as_float
from ....shared.workout_status import is_workout_completed

RAW_CACHE_VERSION = 4

_WORKOUT_FIELDS = (
    "id",
    "date",
    "title",
    "sport",
    "type",
    "tags",
    "duration_actual",
    "distance_actual_km",
    "tss_actual",
)
_EVENT_FIELDS = (
    "id",
    "name",
    "eventDate",
    "date",
    "eventType",
    "event_type",
    "atpPriority",
    "priority",
    "raceTypeDuration",
    "distance",
    "distanceUnits",
    "goals",
    "workouts",
    "results",
)


def plan_fetch_window(
    raw_cache: Optional[dict[str, Any]],
    *,
    year: int,
    start: date,
    end: date,
    is_complete: bool,
    force_full: bool = False,
) -> tuple[str, Optional[date], Optional[date]]:
    """Determines `('cached' | 'incremental' | 'full', fetch_start, fetch_end)` for calendar year `year`.

    - `force_full=True` always re-fetches `[start, end]`.
    - Finished years already cached as `is_complete=True` return `('cached', None, None)` (zero TP calls).
    - Unfinished years with an existing raw snapshot fetch ONLY `[last_computed_date, end]` so workouts
      strictly before `last_computed_date` are never re-pulled from TrainingPeaks.
    """
    if force_full:
        return "full", start, end
    if (
        not isinstance(raw_cache, dict)
        or raw_cache.get("version") != RAW_CACHE_VERSION
        or raw_cache.get("year") != year
    ):
        return "full", start, end

    if is_complete and raw_cache.get("is_complete") is True:
        return "cached", None, None

    last_computed = parse_date(raw_cache.get("last_computed_date") or raw_cache.get("as_of_date"))
    if not last_computed or last_computed < start or last_computed > end:
        return "full", start, end

    fetch_start = max(start, last_computed)
    return "incremental", fetch_start, end


def compact_workout(w: dict[str, Any]) -> dict[str, Any]:
    """Keeps only the minimal fields required for annual aggregation and structured race detection."""
    out: dict[str, Any] = {}
    for k in _WORKOUT_FIELDS:
        if k in w and w[k] is not None:
            out[k] = w[k]
    if "id" in out:
        out["id"] = str(out["id"])
    if "date" in out:
        out["date"] = str(out["date"])[:10]
    return out


def compact_event(ev: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _EVENT_FIELDS:
        if k in ev and ev[k] is not None:
            out[k] = ev[k]
    if "id" in out:
        out["id"] = str(out["id"])
    return out


def compact_race_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Extracts only the lightweight fields `enrich_races_with_details` consumes."""
    metrics = detail.get("metrics") if isinstance(detail.get("metrics"), dict) else {}
    hr = as_float(detail.get("avg_hr")) or as_float(metrics.get("avg_hr")) or as_float(metrics.get("heart_rate_avg"))
    dur = as_float(metrics.get("duration_actual"))
    dist = as_float(metrics.get("distance_actual_km"))
    comment = str(detail.get("new_comment") or "").strip()[:120] or None
    return {
        "avg_hr": hr,
        "new_comment": comment,
        "metrics": {
            "duration_actual": dur,
            "distance_actual_km": dist,
        },
    }


def _event_iso_date(ev: dict[str, Any]) -> str:
    d = parse_date(ev.get("eventDate") or ev.get("date"))
    return iso_date(d) if d else ""


def merge_workouts(
    cached_workouts: list[dict[str, Any]],
    fresh_workouts: list[dict[str, Any]],
    *,
    window_start: date,
    delta_start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Keeps cached workouts in `[window_start, delta_start)`, replaces `[delta_start, end]` with fresh data."""
    win_iso, delta_iso, end_iso = iso_date(window_start), iso_date(delta_start), iso_date(end)
    fresh_in_window = [
        compact_workout(w)
        for w in (fresh_workouts or [])
        if is_workout_completed(w) and win_iso <= str(w.get("date") or "")[:10] <= end_iso
    ]
    fresh_ids = {str(w["id"]) for w in fresh_in_window if w.get("id") is not None}

    kept_cached = [
        compact_workout(w)
        for w in (cached_workouts or [])
        if is_workout_completed(w)
        and win_iso <= str(w.get("date") or "")[:10] < delta_iso
        and str(w.get("id") or "") not in fresh_ids
    ]
    merged = kept_cached + fresh_in_window
    merged.sort(key=lambda w: (str(w.get("date") or ""), str(w.get("id") or "")))
    return merged


def merge_events(
    cached_events: list[dict[str, Any]],
    fresh_events: Optional[list[dict[str, Any]]],
    *,
    window_start: date,
    delta_start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Merges TP events, preserving cached events in `[delta_start, end]` if `fresh_events` is None (error)."""
    win_iso, delta_iso, end_iso = iso_date(window_start), iso_date(delta_start), iso_date(end)
    if fresh_events is None:
        return [
            compact_event(ev)
            for ev in (cached_events or [])
            if isinstance(ev, dict) and win_iso <= _event_iso_date(ev) <= end_iso
        ]

    fresh_in_window = [
        compact_event(ev)
        for ev in fresh_events
        if isinstance(ev, dict) and win_iso <= _event_iso_date(ev) <= end_iso
    ]
    fresh_ids = {str(ev["id"]) for ev in fresh_in_window if ev.get("id") is not None}
    kept_cached = [
        compact_event(ev)
        for ev in (cached_events or [])
        if isinstance(ev, dict)
        and win_iso <= _event_iso_date(ev) < delta_iso
        and (ev.get("id") is None or str(ev["id"]) not in fresh_ids)
    ]
    merged = kept_cached + fresh_in_window
    merged.sort(key=lambda ev: (_event_iso_date(ev), str(ev.get("id") or "")))
    return merged


def serialize_health(dated_metrics: dict[str, list[tuple[date, float]]]) -> dict[str, list[list[Any]]]:
    """Converts `{key: [(date, val), ...]}` to Firestore-safe `{key: [['YYYY-MM-DD', val], ...]}`."""
    out: dict[str, list[list[Any]]] = {}
    for key in ("hrv", "rhr", "sleep"):
        rows: list[list[Any]] = []
        for d, val in (dated_metrics or {}).get(key) or []:
            parsed = parse_date(d)
            num = as_float(val)
            if parsed and num is not None:
                rows.append([iso_date(parsed), round(num, 2)])
        out[key] = rows
    return out


def deserialize_health(raw_health: Optional[dict[str, Any]]) -> dict[str, list[tuple[date, float]]]:
    """Restores Firestore-stored `{key: [['YYYY-MM-DD', val], ...]}` into `[(date, float), ...]`."""
    out: dict[str, list[tuple[date, float]]] = {"hrv": [], "rhr": [], "sleep": []}
    if not isinstance(raw_health, dict):
        return out
    for key in ("hrv", "rhr", "sleep"):
        pairs: list[tuple[date, float]] = []
        for item in raw_health.get(key) or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                d = parse_date(item[0])
                v = as_float(item[1])
                if d and v is not None:
                    pairs.append((d, v))
        out[key] = pairs
    return out


def merge_health(
    cached_health: dict[str, list[tuple[date, float]]],
    fresh_health: dict[str, list[tuple[date, float]]],
    *,
    window_start: date,
    delta_start: date,
    end: date,
) -> dict[str, list[tuple[date, float]]]:
    """Merges dated health metrics, keeping `[window_start, delta_start)` and replacing `[delta_start, end]`."""
    merged: dict[str, list[tuple[date, float]]] = {}
    for key in ("hrv", "rhr", "sleep"):
        by_day: dict[date, float] = {}
        for d, val in (cached_health or {}).get(key) or []:
            if window_start <= d < delta_start:
                by_day[d] = val
        for d, val in (fresh_health or {}).get(key) or []:
            if window_start <= d <= end:
                by_day[d] = val
        merged[key] = sorted(by_day.items(), key=lambda pair: pair[0])
    return merged


def serialize_daily_pmc(daily_pmc: list[dict[str, Any]]) -> list[list[Any]]:
    """Compact Firestore representation of daily PMC rows: `[['YYYY-MM-DD', ctl, tss], ...]`."""
    rows: list[list[Any]] = []
    for row in daily_pmc or []:
        if not isinstance(row, dict):
            continue
        d_str = str(row.get("date") or "")[:10]
        ctl = as_float(row.get("ctl"))
        if d_str and ctl is not None:
            tss = as_float(row.get("tss")) or 0.0
            rows.append([d_str, round(ctl, 2), round(tss, 1)])
    return rows


def deserialize_daily_pmc(raw_pmc: Any) -> list[dict[str, Any]]:
    """Restores Firestore-stored daily PMC rows into `[{'date': ..., 'ctl': ..., 'tss': ...}, ...]`."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw_pmc, list):
        return out
    for item in raw_pmc:
        if isinstance(item, dict) and item.get("date") and item.get("ctl") is not None:
            out.append({
                "date": str(item["date"])[:10],
                "ctl": as_float(item.get("ctl")),
                "tss": as_float(item.get("tss")) or 0.0,
            })
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            d_str = str(item[0])[:10]
            ctl = as_float(item[1])
            if d_str and ctl is not None:
                tss = as_float(item[2]) if len(item) >= 3 else 0.0
                out.append({"date": d_str, "ctl": ctl, "tss": tss or 0.0})
    return out


def merge_daily_pmc(
    cached_pmc: list[dict[str, Any]],
    fresh_pmc: list[dict[str, Any]],
    *,
    window_start: date,
    delta_start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Keeps cached daily PMC in `[window_start, delta_start)` and replaces `[delta_start, end]`."""
    win_iso, delta_iso, end_iso = iso_date(window_start), iso_date(delta_start), iso_date(end)
    by_day: dict[str, dict[str, Any]] = {}
    for row in cached_pmc or []:
        d_str = str(row.get("date") or "")[:10]
        ctl = as_float(row.get("ctl"))
        if win_iso <= d_str < delta_iso and ctl is not None:
            by_day[d_str] = {"date": d_str, "ctl": ctl, "tss": as_float(row.get("tss")) or 0.0}
    for row in fresh_pmc or []:
        d_str = str(row.get("date") or "")[:10]
        ctl = as_float(row.get("ctl"))
        if win_iso <= d_str <= end_iso and ctl is not None:
            by_day[d_str] = {"date": d_str, "ctl": ctl, "tss": as_float(row.get("tss")) or 0.0}
    return [by_day[d] for d in sorted(by_day.keys())]


def build_raw_snapshot(
    *,
    year: int,
    window_start: date,
    end: date,
    is_complete: bool,
    workouts: list[dict[str, Any]],
    events: list[dict[str, Any]],
    dated_metrics: dict[str, list[tuple[date, float]]],
    daily_pmc: list[dict[str, Any]],
    race_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assembles the compact `users/{runner_id}/cache/year_review_raw_{year}` Firestore document."""
    valid_wids = {str(w.get("id") or "") for w in workouts if w.get("id") is not None}
    pruned_details = {
        wid: compact_race_detail(detail)
        for wid, detail in (race_details or {}).items()
        if wid in valid_wids and isinstance(detail, dict)
    }
    end_iso = iso_date(end)
    return {
        "version": RAW_CACHE_VERSION,
        "year": int(year),
        "is_complete": bool(is_complete),
        "window_start": iso_date(window_start),
        "last_computed_date": end_iso,
        "as_of_date": end_iso,
        "workouts": [compact_workout(w) for w in workouts],
        "events": [compact_event(ev) for ev in events],
        "health": serialize_health(dated_metrics),
        "daily_pmc": serialize_daily_pmc(daily_pmc),
        "race_details": pruned_details,
    }
