"""One-off repair: planned average speed (`velocityPlanned`, the planned pace in TrainingPeaks) that went
stale when tp_mcp < 2.0.2 updated a workout's planned distance/duration without recomputing it.

Walks the calendar one week at a time. For every planned (not completed) workout with a planned distance
and duration it compares the stored `velocityPlanned` with distance / duration. Dry run by default;
`--apply` GETs each mismatching workout, sets only `velocityPlanned` and PUTs it back.

Run with the tp_mcp environment (it holds the TrainingPeaks credentials):
    trainingpeaks-mcp/.venv/bin/python scripts/fix_planned_velocity.py --start 2026-11-11 --end 2027-07-11
    trainingpeaks-mcp/.venv/bin/python scripts/fix_planned_velocity.py --start 2026-11-11 --end 2027-07-11 --apply
"""

import argparse
import asyncio
from datetime import date, timedelta
from typing import Any, Optional

from tp_mcp.client import TPClient

REL_TOL = 0.01  # stored vs derived speed difference that counts as stale
WEEK_PAUSE_S = 0.5  # be gentle with the TrainingPeaks API between weeks


def _num(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def derived_velocity(workout: dict) -> Optional[float]:
    metres, hours = _num(workout.get("distancePlanned")), _num(workout.get("totalTimePlanned"))
    if not metres or not hours or metres <= 0 or hours <= 0:
        return None
    return metres / (hours * 3600.0)


def is_completed(workout: dict) -> bool:
    return any((_num(workout.get(k)) or 0) > 0 for k in ("totalTime", "distance", "tssActual"))


def is_stale(workout: dict) -> bool:
    derived, stored = derived_velocity(workout), _num(workout.get("velocityPlanned"))
    if derived is None:
        return False
    return stored is None or abs(stored - derived) > REL_TOL * derived


def pace(velocity: Optional[float]) -> str:
    if not velocity:
        return "–"
    seconds = round(1000.0 / velocity)
    return f"{seconds // 60}:{seconds % 60:02d}/km"


def weeks(start: date, end: date):
    cursor = start
    while cursor <= end:
        week_end = min(cursor + timedelta(days=6), end)
        yield cursor, week_end
        cursor = week_end + timedelta(days=1)


async def fix_one(client: TPClient, athlete_id: int, workout_id: Any) -> str:
    endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
    got = await client.get(endpoint)
    if got.is_error or not isinstance(got.data, dict):
        return f"GET failed: {got.message}"
    workout = got.data
    if is_completed(workout) or not is_stale(workout):
        return "skipped (no longer stale)"
    workout["velocityPlanned"] = derived_velocity(workout)
    put = await client.put(endpoint, json=workout)
    return f"PUT failed: {put.message}" if put.is_error else "fixed"


async def main(start: date, end: date, apply: bool) -> None:
    total = stale_count = fixed = 0
    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            raise SystemExit("Could not get athlete ID: re-authenticate tp_mcp.")
        for week_start, week_end in weeks(start, end):
            resp = await client.get(f"/fitness/v6/athletes/{athlete_id}/workouts/{week_start}/{week_end}")
            if resp.is_error:
                print(f"[{week_start} – {week_end}] list failed: {resp.message}")
                continue
            listed = resp.data if isinstance(resp.data, list) else []
            planned = [w for w in listed if isinstance(w, dict) and not is_completed(w)]
            stale = [w for w in planned if is_stale(w)]
            total += len(planned)
            stale_count += len(stale)
            print(f"[{week_start} – {week_end}] {len(planned)} planned, {len(stale)} stale")
            for w in stale:
                line = (f"    {str(w.get('workoutDay', ''))[:10]}  {w.get('workoutId')}  "
                        f"{pace(_num(w.get('velocityPlanned')))} -> {pace(derived_velocity(w))}  {w.get('title')}")
                if apply:
                    outcome = await fix_one(client, athlete_id, w.get("workoutId"))
                    fixed += outcome == "fixed"
                    line += f"  [{outcome}]"
                print(line)
            await asyncio.sleep(WEEK_PAUSE_S)
    verb = f"fixed {fixed}" if apply else "dry run, nothing written (use --apply)"
    print(f"\n{total} planned workouts checked, {stale_count} stale; {verb}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true", help="write the fixes (default: dry run)")
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end, args.apply))
