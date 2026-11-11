"""One-off repair: planned tempo / threshold / interval runs whose builder lost its strides.

Walks the calendar one week at a time. For every planned (not completed) Run whose builder is a quality
session without strides, it inserts the default strides block (4x 20" / 40") right after the warm-up with
the coach's own helpers (shared/strides.py) and recomputes distance, duration and
TSS from the new builder. Long runs are excluded. Dry run by default; `--apply` writes each one through
tp_mcp's tp_update_workout (2.0.2+, which also keeps the planned pace consistent).

Run from the workspace root with the app venv (imports the vendored tp_mcp source for the write):
    venv/bin/python running_coach/scripts/fix_missing_strides.py --start 2026-11-11 --end 2027-07-11
    venv/bin/python running_coach/scripts/fix_missing_strides.py --start 2026-11-11 --end 2027-07-11 --apply
"""

import argparse
import asyncio
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trainingpeaks-mcp" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # workspace root: the running_coach package

from tp_mcp.tools.settings import tp_get_athlete_settings  # noqa: E402
from tp_mcp.tools.workouts import tp_get_workout, tp_get_workouts, tp_update_workout  # noqa: E402

from running_coach.shared.strides import ADDED, ensure_strides  # noqa: E402
from running_coach.shared.workout_builder import (  # noqa: E402
    builder_summary,
    builder_totals,
    has_builder,
)
from running_coach.shared.athlete_settings import sport_thresholds  # noqa: E402
from running_coach.shared.sports import RUN_SPORTS  # noqa: E402
from running_coach.shared.workout_status import is_workout_completed  # noqa: E402

WEEK_PAUSE_S = 0.5  # be gentle with the TrainingPeaks API between weeks


def weeks(start: date, end: date):
    cursor = start
    while cursor <= end:
        week_end = min(cursor + timedelta(days=6), end)
        yield cursor, week_end
        cursor = week_end + timedelta(days=1)


async def main(start: date, end: date, apply: bool, skip: set[str]) -> None:
    thr = sport_thresholds(await tp_get_athlete_settings(), "Run")
    if not thr.get("threshold_speed"):
        raise SystemExit("No run threshold pace in TrainingPeaks: cannot place strides targets.")
    checked = missing = fixed = 0
    for week_start, week_end in weeks(start, end):
        listed = await tp_get_workouts(start_date=week_start.isoformat(), end_date=week_end.isoformat())
        if listed.get("isError"):
            print(f"[{week_start} – {week_end}] list failed: {listed.get('message')}")
            continue
        runs = [w for w in listed.get("workouts") or []
                if str(w.get("sport") or "").lower() in RUN_SPORTS and not is_workout_completed(w)
                and str(w.get("id")) not in skip]
        week_missing = []
        for w in runs:
            detail = await tp_get_workout(workout_id=str(w["id"]))
            native = detail.get("structured_workout") if isinstance(detail, dict) else None
            if not has_builder(native):
                continue
            checked += 1
            new, status = ensure_strides({"sport": "Run", "title": w.get("title")}, native, None, thr)
            if status == ADDED:
                week_missing.append((w, native, new))
        missing += len(week_missing)
        print(f"[{week_start} – {week_end}] {len(runs)} planned runs, {len(week_missing)} quality runs without strides")
        for w, native, new in week_missing:
            totals = builder_totals(new, thr)
            print(f"    {w['date']}  {w['id']}  {w.get('title')}")
            print(f"        before: {builder_summary(native, thr)}  ({w.get('distance_planned_km')} km)")
            print(f"        after:  {builder_summary(new, thr)}  ({totals['distance_km']} km, "
                  f"{totals['duration_minutes']} min, TSS {totals['tss_planned']})")
            if apply:
                kwargs = {k: v for k, v in (("distance_km", totals["distance_km"]),
                                            ("duration_minutes", totals["duration_minutes"]),
                                            ("tss_planned", totals["tss_planned"])) if v is not None}
                result = await tp_update_workout(workout_id=str(w["id"]), structured_workout=new, **kwargs)
                ok = isinstance(result, dict) and result.get("success")
                fixed += bool(ok)
                print("        [fixed]" if ok else f"        [FAILED: {result.get('message')}]")
        await asyncio.sleep(WEEK_PAUSE_S)
    verb = f"fixed {fixed}" if apply else "dry run, nothing written (use --apply)"
    print(f"\n{checked} planned runs with a builder checked, {missing} quality runs without strides; {verb}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true", help="write the fixes (default: dry run)")
    parser.add_argument("--skip", action="append", default=[], metavar="WORKOUT_ID",
                        help="workout id to leave untouched (repeatable)")
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end, args.apply, set(args.skip)))
