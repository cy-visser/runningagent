"""Long-run and 12-week completed volume facts shared across plan audit, plan builder, and trend analysis.

There is deliberately no computed long-run or weekly-volume target, floor, or cap: tools report measured
facts (12-week weekly km history, peak, sustained streak, recent active mean, longest runs, week-over-week
change) and cache the 12-week completed totals in Firestore (`users/{user_id}/cache/volume_history`, 28-day
refresh) so the coach reasons directly toward the goal / north star.
"""

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ..integrations import firestore
from ..integrations.trainingpeaks import tp_calls
from .dates import get_now_utc, iso_date, monday_of
from .runner_identity import profile_user_id
from .weekly_buckets import build_week_buckets
from .workout_status import is_workout_completed

logger = logging.getLogger(__name__)

LONG_RUN_HISTORY_WEEKS = 6       # recent complete weeks shown for per-week longest-run detail
VOLUME_HISTORY_WEEKS = 12        # 12 complete weeks (84 days <= 89-day TP chunk): survives taper + race + recovery
VOLUME_CACHE_MAX_AGE = timedelta(days=28)
STREAK_STEP_KM = 10
MIN_STREAK_WEEKS = 3


def fmt_km(value: float) -> str:
    return f"{value:g}"


def fmt_duration(hours: Optional[float]) -> str:
    """'1:28' (h:mm), or '' when unknown."""
    if not hours or hours <= 0:
        return ""
    minutes = round(hours * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Percentage change from `old` to `new` (1 decimal), or None when `old` has no volume.

    A fact only: whether a change is too steep is the coach's judgement, never a coded limit.
    """
    if not old or old <= 0 or new is None:
        return None
    return round((new / old - 1) * 100, 1)


def history_window(today: date, weeks: int = LONG_RUN_HISTORY_WEEKS) -> tuple[date, date]:
    """(first day, last day) of the `weeks` complete ISO weeks before `today`'s week."""
    end = monday_of(today) - timedelta(days=1)
    return end - timedelta(weeks=weeks) + timedelta(days=1), end


def recent_long_runs(
    workouts: Optional[list[dict]], today: date, weeks: int = LONG_RUN_HISTORY_WEEKS
) -> list[dict]:
    """[{'week', 'km', 'hours', 'week_km', 'strength_count', 'bike_count'}] per complete week, oldest first."""
    start, end = history_window(today, weeks)
    done = [w for w in workouts or [] if is_workout_completed(w)]
    buckets = sorted(build_week_buckets(done, start, end).values(), key=lambda w: w["start_date"])
    return [
        {
            "week": iso_date(w["start_date"]),
            "km": round(w["long_km"] or 0.0, 1),
            "hours": round(float(w["long_duration_h"]), 3) if w.get("long_duration_h") else None,
            "week_km": round(w["total_distance_km"] or 0.0, 1),
            "strength_count": int(w.get("strength_count") or 0),
            "bike_count": int(w.get("bike_count") or 0),
        }
        for w in buckets
    ]


def _parse_utc(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str) and ts.strip():
        try:
            dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def is_volume_cache_fresh(doc: Optional[dict[str, Any]], now_utc: Optional[datetime] = None) -> bool:
    """True when `doc` holds a non-empty `weeks` list and `fetched_at` is at most 28 days old."""
    if not isinstance(doc, dict) or not isinstance(doc.get("weeks"), list) or not doc["weeks"]:
        return False
    fetched_at = _parse_utc(doc.get("fetched_at"))
    if fetched_at is None:
        return False
    now = now_utc or get_now_utc()
    age = now - fetched_at
    return timedelta(0) <= age <= VOLUME_CACHE_MAX_AGE


async def read_cached_volume_history(user_id: Optional[str]) -> Optional[dict[str, Any]]:
    """Best-effort Firestore point-read of `users/{user_id}/cache/volume_history`."""
    if not user_id:
        return None
    try:
        return await firestore.get_cached_volume_history(user_id)
    except Exception as exc:
        logger.warning("Ignoring Firestore volume-history cache read error for %s: %s", user_id, exc)
        return None


_UNSET = object()


async def get_or_fetch_volume_history(
    tool_context: ToolContext,
    profile: Optional[dict],
    today: date,
    cached_doc: Any = _UNSET,
    prefetched_workouts: Optional[list[dict]] = None,
    prefetched_start: Optional[date] = None,
) -> Optional[list[dict]]:
    """Returns 12-week completed volume/long-run entries from Firestore cache (<= 28 days old) or TrainingPeaks.

    When missing or older than 28 days, pulls only the uncached completed days from TrainingPeaks, writes
    the aggregated 12-week totals + `fetched_at` UTC timestamp to Firestore, and returns them.
    """
    user_id = profile_user_id(profile or {}) if profile else None
    now_utc = get_now_utc()
    doc = await read_cached_volume_history(user_id) if cached_doc is _UNSET else cached_doc
    if is_volume_cache_fresh(doc, now_utc):
        return list(doc["weeks"])

    h_start, h_end = history_window(today, VOLUME_HISTORY_WEEKS)
    fetch_end = min(h_end, prefetched_start - timedelta(days=1)) if prefetched_start else h_end
    fetched: list[dict] = []
    if h_start <= fetch_end:
        try:
            fetched = await tp_calls.fetch_workouts(tool_context, iso_date(h_start), iso_date(fetch_end))
        except Exception as exc:
            logger.warning("Failed to refresh 12-week volume history from TrainingPeaks: %s", exc)
            if isinstance(doc, dict) and isinstance(doc.get("weeks"), list) and doc["weeks"]:
                return list(doc["weeks"])
            return None

    combined = fetched + list(prefetched_workouts or [])
    entries = recent_long_runs(combined, today, weeks=VOLUME_HISTORY_WEEKS)
    if user_id:
        payload = {
            "fetched_at": now_utc.isoformat(),
            "as_of_monday": iso_date(monday_of(today)),
            "weeks": entries,
        }
        try:
            await firestore.save_volume_history(user_id, payload)
        except Exception as exc:
            logger.warning("Ignoring Firestore volume-history cache write error for %s: %s", user_id, exc)
    return entries


def volume_history_facts(entries: list[dict]) -> dict:
    """Pure arithmetic summary of completed weekly running km across `entries` (oldest first)."""
    kms = [round(float(e.get("week_km") or 0.0), 1) for e in entries]
    peak = max(kms, default=0.0)
    recent_active = [k for k in kms[-4:] if k > 0]
    recent_mean = round(sum(recent_active) / len(recent_active), 1) if recent_active else None
    top_tier = int(peak // STREAK_STEP_KM) * STREAK_STEP_KM
    streak_level: Optional[int] = None
    streak_len = 0
    for level in range(top_tier, STREAK_STEP_KM - 1, -STREAK_STEP_KM):
        best = cur = 0
        for k in kms:
            cur = cur + 1 if k >= level else 0
            best = max(best, cur)
        if best >= MIN_STREAK_WEEKS:
            streak_level, streak_len = level, best
            break
    return {
        "peak_km": peak if peak > 0 else None,
        "streak_level_km": streak_level,
        "streak_weeks": streak_len,
        "recent_active_mean_km": recent_mean,
    }


def format_volume_history_facts(entries: list[dict]) -> str:
    """'peak 74 km; 3-wk streak >= 70 km; recent 4-wk active mean 55 km', or '' when no runs."""
    facts = volume_history_facts(entries)
    if not facts["peak_km"]:
        return ""
    parts = [f"peak {fmt_km(round(facts['peak_km'], 1))} km"]
    if facts["streak_level_km"]:
        parts.append(f"{facts['streak_weeks']}-wk streak >= {facts['streak_level_km']} km")
    if facts["recent_active_mean_km"]:
        parts.append(f"recent 4-wk active mean {fmt_km(round(facts['recent_active_mean_km'], 1))} km")
    return "; ".join(parts)


def format_weekly_km_history(entries: list[dict]) -> str:
    """'48 · 52 · – · 55' running km per history week (oldest first; '–' = no runs), or ''."""
    if not any(e.get("week_km") for e in entries):
        return ""
    return " · ".join(f"{e['week_km']:.0f}" if e.get("week_km") else "–" for e in entries)


def format_history(entries: list[dict]) -> str:
    """'12 km 1:05 · 14 km 1:16 · – · 16 km 1:28' (oldest first; '–' = no run that week), or ''."""
    if not any(e.get("km") for e in entries):
        return ""
    parts = []
    for e in entries:
        if not e.get("km"):
            parts.append("–")
            continue
        dur = fmt_duration(e.get("hours"))
        parts.append(f"{fmt_km(e['km'])} km" + (f" {dur}" if dur else ""))
    return " · ".join(parts)


def week_long_run_facts(long_km: Optional[float], hours: Optional[float], week_km: Optional[float]) -> str:
    """'16 km (1:28, 34% of the week's running km)', or 'no run'."""
    if not long_km:
        return "no run"
    extras = [d for d in (fmt_duration(hours),) if d]
    if week_km:
        extras.append(f"{round(long_km / week_km * 100)}% of the week's running km")
    return f"{fmt_km(round(long_km, 1))} km" + (f" ({', '.join(extras)})" if extras else "")
