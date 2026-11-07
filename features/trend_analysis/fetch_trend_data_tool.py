import asyncio
import logging
from datetime import timedelta

from google.adk.tools import FunctionTool, ToolContext

from ...integrations import firestore
from ...integrations.trainingpeaks import tp_calls
from ...shared.athlete_settings import extract_hr_zones, extract_thresholds
from ...shared.dates import get_today_date, iso_date
from ...shared.goal_distance import resolve_goal_distance
from ...shared.goal_plan import current_goal
from ...shared.goal_projection.goal_trajectory import summarize_fitness
from ...shared.goal_projection.race_projection import build_goal_projection
from ...shared.north_star_targets import recent_volume_baseline
from ...shared.parallel_fetch import gather_labeled
from ...shared.runner_identity import profile_user_id
from ...shared.sports import NON_TRAINING_SPORTS, RUN_SPORTS
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.health_metrics import HEALTH_BASELINE_DAYS
from ...shared.long_run_facts import LONG_RUN_HISTORY_WEEKS, format_history
from ...shared.workout_status import is_workout_completed
from .helpers.goal_progress import format_goal_context, goal_progress
from .helpers.load_capacity import (
    add_load_ratio,
    capacity_outlook,
    format_levels_table,
    format_outlook,
    ratio_vs_next_hrv,
    volume_levels,
)
from .helpers.pacing import analyse_pacing, format_pacing_details, format_pacing_tables
from .helpers.progress import format_progress_table, progress_summary
from .helpers.training_log_gapfill import GAPFILL_CONCURRENCY, gapfill_one
from .helpers.training_patterns import format_patterns, training_patterns
from .helpers.web_report import TREND_REPORT_STATE_KEY, trend_report_data
from .helpers.weekly_rows import (
    LLM_RECENT_WEEKS,
    format_weekly_table,
    key_run_label,
    llm_comments,
    weekly_rows,
)

logger = logging.getLogger(__name__)

TREND_MIN_WEEKS, TREND_MAX_WEEKS = 6, 52


async def fetch_trend_data(tool_context: ToolContext, weeks: int = 26) -> str:
    """Long-horizon training-log trends: progress, weekly load capacity, pacing, training patterns and
    progress toward the goal / north star.

    Args:
        weeks: Weeks to analyse (6-52, default 26).
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."
    user_id = profile_user_id(profile)
    if not user_id:
        return "Error: Name not found in profile."

    weeks = max(TREND_MIN_WEEKS, min(TREND_MAX_WEEKS, int(weeks or 26)))
    today = get_today_date()
    start = today - timedelta(weeks=weeks)
    start = start - timedelta(days=start.weekday())          # whole ISO weeks
    health_start = start - timedelta(days=HEALTH_BASELINE_DAYS)

    raw = await gather_labeled({
        "workouts": tp_calls.fetch_workouts_range(tool_context, start, today),
        "records": firestore.list_training_records(user_id, iso_date(start), iso_date(today)),
        "fitness PMC": tp_calls.run_tp_tool(tool_context, "tp_get_fitness", start_date=iso_date(start), end_date=iso_date(today)),
        "health": tp_calls.fetch_metrics_range(tool_context, health_start, today),
        "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
    })
    if raw["records"] is None:
        return "Error: Could not read the training log from Firestore; try again later."
    records = raw["records"]
    daily_pmc = coerce_mcp_payload(raw["fitness PMC"]).get("daily_data") or [] if raw["fitness PMC"] else []
    dated_metrics = raw["health"] or {}
    thresholds = extract_thresholds(raw["athlete settings"])

    # Gap-fill: completed workouts without a record go through the same write path as analyze_workout.
    known = {r.get("workout_id") for r in records}
    missing = sorted((
        w for w in raw["workouts"] or []
        if is_workout_completed(w) and (w.get("sport") or "") not in NON_TRAINING_SPORTS
        and str(w.get("id")) not in known
    ), key=lambda w: str(w.get("date") or ""), reverse=True)    # newest first: recent weeks matter most
    sem = asyncio.Semaphore(GAPFILL_CONCURRENCY)
    filled = await asyncio.gather(*(
        gapfill_one(tool_context, sem, profile, w, thresholds=thresholds,
                    daily_pmc=daily_pmc, dated_metrics=dated_metrics)
        for w in missing
    ))
    new = [r for r in filled if r]
    records = sorted(records + new, key=lambda r: (r.get("date") or "", r.get("workout_id") or ""))
    unrecorded = [str(w.get("date") or "") for w, r in zip(missing, filled) if not r]

    goal_label = resolve_goal_distance(current_goal(profile, today)["training_goal"])
    zones = extract_hr_zones(raw["athlete settings"])
    lthr = thresholds.get("lthr")
    lt1_hr = zones[1]["max"] if len(zones) >= 2 else None          # LT1 = top of TP HR zone 2
    rows = add_load_ratio(weekly_rows(records, daily_pmc, dated_metrics, start, today, unrecorded,
                                      goal_label=goal_label, lthr=lthr, lt1_hr=lt1_hr))
    progress = progress_summary(rows, goal_label)
    levels = volume_levels(rows)
    outlook = capacity_outlook(rows, levels)
    rho, n_pairs = ratio_vs_next_hrv(rows)
    pacing = analyse_pacing(records, thresholds, zones, today)
    patterns = training_patterns(rows)

    # Goal / north-star progress: the same evidence-based projection as the check-in (cache-first).
    fitness = summarize_fitness(raw["fitness PMC"], profile, today)
    try:
        race_projection = await build_goal_projection(
            tool_context, goal_label, profile, raw["workouts"] or [], fitness,
            raw["athlete settings"], dated_metrics, today,
        )
    except Exception:  # the projection must never break the trend report
        logger.exception("Goal projection failed in fetch_trend_data")
        race_projection = {"goal_label": goal_label, "projection": None}
    goal = goal_progress(profile, today, rows, fitness, race_projection,
                         volume_baseline=recent_volume_baseline(raw["workouts"], today))

    # The report renders charts and tables from this payload; the coach only writes recommendations.
    tool_context.state[TREND_REPORT_STATE_KEY] = trend_report_data(
        start, today, rows, progress, levels, outlook, key_run_label=key_run_label(goal_label),
        goal_progress=goal, paces=pacing.get("paces"),
    )

    progress_table = format_progress_table(progress)
    if progress_table and pacing.get("lthr_check"):
        progress_table += ("\n\n_Pace @ LT2 uses the TrainingPeaks LTHR; see the LTHR check line for the "
                           "sustained-effort evidence._")
    tables = "\n\n".join(t for t in (
        progress_table, format_levels_table(levels), format_pacing_tables(pacing)
    ) if t)

    runs = sum(1 for r in records if str(r.get("sport") or "").lower() in RUN_SPORTS)
    with_laps = sum(1 for r in records if r.get("laps"))
    comments = llm_comments(rows)
    long_run_line = format_long_run_history(rows)
    capacity = format_outlook(outlook, rho, n_pairs) + (f"\n\n{long_run_line}" if long_run_line else "")
    recent = rows[-LLM_RECENT_WEEKS:]
    sections = [
        f"## Trend data: {iso_date(start)} to {iso_date(today)} ({weeks} weeks)",
        f"Coverage: {len(records)} workouts in the training log ({runs} runs, {with_laps} with lap data); "
        f"{len(new)} added by gap-fill now, {len(unrecorded)} could not be recorded now (no data, still syncing, "
        "or a TrainingPeaks error such as a rate limit; retried on the next call). Weeks with unrecorded "
        "workouts are marked and excluded from progress, capacity and pattern conclusions.",
        "### Goal context\n" + format_goal_context(goal, profile, today),
        tables,
        f"### Weekly rows (last {len(recent)} of {len(rows)} weeks; the summaries above cover all weeks "
        "and the web charts show every week)\n" + format_weekly_table(recent),
        "### Load capacity\n" + capacity,
        "### Pacing\n" + format_pacing_details(pacing),
        "### Training patterns\n" + format_patterns(patterns),
    ]
    if comments:
        sections.append(
            f"### Athlete comments (raw; last {LLM_RECENT_WEEKS} weeks plus older niggles)\n"
            + "\n".join(f"- {c}" for c in comments)
        )
    return "\n\n".join(sections)


def format_long_run_history(rows: list[dict]) -> str:
    """Long-run facts for the coach (no computed target): longest run of the last complete weeks."""
    recent = [{"km": r.get("long_km"), "hours": None} for r in rows if r.get("complete")][-LONG_RUN_HISTORY_WEEKS:]
    history = format_history(recent) or "no complete weeks with recorded runs"
    return (f"Long-run history (longest run of each of the last {len(recent)} complete weeks, oldest first): "
            f"{history}. There is no computed long-run target: reason any long-run advice from this history, "
            "the weekly volume and the time to the goal / north-star race.")


fetch_trend_data_tool = FunctionTool(fetch_trend_data)
