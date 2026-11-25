#!/usr/bin/env python3
"""One-time script to fix inflated historical TrainingPeaks running TSS (Power TSS -> Pace rTSS).

Root cause fixed:
    Completed Run workouts (`workoutTypeValueId == 3`) scored with `tssSource == 1` (Power TSS)
    against TrainingPeaks' default 220 W cycling FTP produced IF ~1.6-1.9 and 250-360 TSS/hour
    from May 2023 through June 1, 2025 (plus one stray run on 2025-09-26).

Recalculation formula (calibrated against Cyrille's normal `tssSource == 2` runs in TP):
    speed = normalizedSpeedActual if present else velocityAverage * 0.9888
    IF    = speed / threshold_speed_ms
    rTSS  = totalTime_hours * (IF ** 2) * 100.0 * 1.11

Default per-year race-calibrated threshold paces (Option A):
    2023: 4:25/km (3.7736 m/s — from 1:36:16 Amsterdam Half Marathon)
    2024: 4:35/km (3.6364 m/s — from 1:40:09 Amsterdam Half Marathon)
    2025: 4:29/km (3.7175 m/s — exact threshold set in TrainingPeaks on June 2, 2025)

Safeguards:
    - Strict filter: ONLY touches `workoutTypeValueId == 3` (Run) with `tssSource == 1`.
      Never touches Bike, Strength, or normal `tssSource == 2` runs.
    - Full JSON backup saved to `/tmp/tp_tss_backup_<timestamp>.json` before any write,
      with `--rollback <backup.json>` to restore original values (and `--remove-backup` to
      delete the temporary backup after verification).
    - Canary verification (`--test-one` or automatic first step of `--apply`): updates 1 workout,
      re-reads `GET /workouts/{id}` and `POST /reporting/performancedata/{day}/{day}` to verify
      TrainingPeaks persisted `tssActual`, `tssSource=2`, and updated PMC CTL before continuing.

Usage:
    # Dry run (read-only)
    python scripts/fix_historical_tss.py --dry-run

    # Canary check on 1 workout
    python scripts/fix_historical_tss.py --test-one

    # Full run (backs up first, runs canary check, updates all matching runs)
    python scripts/fix_historical_tss.py --apply --remove-backup

    # Rollback from backup file
    python scripts/fix_historical_tss.py --rollback /tmp/tp_tss_backup_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from running_coach.integrations.trainingpeaks import credentials, tp_calls

logger = logging.getLogger("fix_historical_tss")

# Empirically calibrated from 126 normal `tssSource == 2` runs in TrainingPeaks (Jun 2025 – Nov 2026).
RTSS_METABOLIC_FACTOR = 1.11
NGP_TO_AVG_SPEED_RATIO = 0.9888

# Per-year race-calibrated threshold paces (Option A).
DEFAULT_YEAR_THRESHOLD_PACES: dict[int, str] = {
    2023: "4:25",
    2024: "4:35",
    2025: "4:29",
}
FALLBACK_THRESHOLD_PACE = "4:29"

RUN_WORKOUT_TYPE_ID = 3
POWER_TSS_SOURCE = 1
PACE_RTSS_SOURCE = 2


def parse_pace_to_ms(pace_str: str) -> float:
    """Converts `'M:SS'` or `'M:SS/km'` to metres per second."""
    cleaned = pace_str.strip().split("/")[0].strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", cleaned)
    if not m:
        raise ValueError(f"Invalid pace '{pace_str}'. Expected 'M:SS' (e.g. '4:29').")
    seconds = int(m.group(1)) * 60 + int(m.group(2))
    if seconds <= 0:
        raise ValueError(f"Pace must be > 0 seconds/km: '{pace_str}'.")
    return 1000.0 / float(seconds)


def threshold_speed_for_date(
    workout_day: str,
    *,
    single_pace: Optional[str] = None,
    year_paces: Optional[dict[int, str]] = None,
) -> float:
    """Resolves threshold running speed (m/s) for a workout date string `'YYYY-MM-DD...'`."""
    if single_pace:
        return parse_pace_to_ms(single_pace)
    yr = int(str(workout_day)[:4])
    mapping = year_paces if year_paces is not None else DEFAULT_YEAR_THRESHOLD_PACES
    pace = mapping.get(yr, FALLBACK_THRESHOLD_PACE)
    return parse_pace_to_ms(pace)


def is_inflated_power_run(workout: dict[str, Any]) -> bool:
    """True strictly for completed Run workouts (`workoutTypeValueId == 3`) scored with Power (`tssSource == 1`)."""
    if workout.get("workoutTypeValueId") != RUN_WORKOUT_TYPE_ID:
        return False
    if workout.get("tssSource") != POWER_TSS_SOURCE:
        return False
    total_time = workout.get("totalTime")
    return isinstance(total_time, (int, float)) and float(total_time) > 0.0


def compute_rtss(
    workout: dict[str, Any],
    *,
    single_pace: Optional[str] = None,
    year_paces: Optional[dict[int, str]] = None,
) -> tuple[float, float, float]:
    """Computes `(new_tss, new_if, effective_speed_ms)` for an inflated Power-scored run.

    Uses `normalizedSpeedActual` when stored by TrainingPeaks; otherwise scales `velocityAverage`
    by `NGP_TO_AVG_SPEED_RATIO` (0.9888, empirically calibrated across 248 runs with both fields).
    """
    hours = float(workout["totalTime"])
    threshold_ms = threshold_speed_for_date(
        str(workout.get("workoutDay") or ""),
        single_pace=single_pace,
        year_paces=year_paces,
    )
    ns = workout.get("normalizedSpeedActual")
    vel = workout.get("velocityAverage")
    if isinstance(ns, (int, float)) and float(ns) > 0:
        speed_ms = float(ns)
    elif isinstance(vel, (int, float)) and float(vel) > 0:
        speed_ms = float(vel) * NGP_TO_AVG_SPEED_RATIO
    else:
        dist = float(workout.get("distance") or 0.0)
        speed_ms = (dist / (hours * 3600.0)) * NGP_TO_AVG_SPEED_RATIO if dist > 0 else 0.0

    if speed_ms <= 0:
        return round(hours * 65.0, 2), 0.765, 0.0

    intensity_factor = round(speed_ms / threshold_ms, 4)
    rtss = round(hours * (intensity_factor ** 2) * 100.0 * RTSS_METABOLIC_FACTOR, 2)
    return rtss, intensity_factor, round(speed_ms, 4)


def snapshot_original_fields(workout: dict[str, Any]) -> dict[str, Any]:
    """Captures the exact fields modified by this script so `--rollback` can restore them verbatim."""
    return {
        "workoutId": workout["workoutId"],
        "workoutDay": str(workout.get("workoutDay") or "")[:10],
        "title": workout.get("title"),
        "tssActual": workout.get("tssActual"),
        "if": workout.get("if"),
        "tssSource": workout.get("tssSource"),
        "normalizedPowerActual": workout.get("normalizedPowerActual"),
    }


def apply_rtss_to_workout_payload(
    existing: dict[str, Any],
    *,
    new_tss: float,
    new_if: float,
) -> dict[str, Any]:
    """Returns a copy of the full TP workout dict with rTSS fields updated cleanly."""
    updated = dict(existing)
    updated["tssActual"] = float(new_tss)
    updated["if"] = float(new_if)
    updated["tssSource"] = PACE_RTSS_SOURCE
    updated["normalizedPowerActual"] = None
    return updated


async def discover_target_workouts(
    client: Any,
    athlete_id: Any,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Lists all completed Run workouts with `tssSource == 1` in `[start_date, end_date]`."""
    found: dict[int, dict[str, Any]] = {}
    for s_iso, e_iso in tp_calls.date_chunks(start_date, end_date):
        resp = await client.get(f"/fitness/v6/athletes/{athlete_id}/workouts/{s_iso}/{e_iso}")
        if resp.is_error:
            raise RuntimeError(f"Failed to list workouts {s_iso}..{e_iso}: {resp.message}")
        for w in resp.data or []:
            if isinstance(w, dict) and is_inflated_power_run(w):
                found[int(w["workoutId"])] = w
    return sorted(found.values(), key=lambda w: (str(w.get("workoutDay") or ""), int(w["workoutId"])))


async def _update_single_workout(
    client: Any,
    athlete_id: Any,
    workout_id: int,
    *,
    new_tss: float,
    new_if: float,
) -> dict[str, Any]:
    """Fetches full workout JSON, patches rTSS fields, and PUTs back to TrainingPeaks."""
    endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
    get_resp = await client.get(endpoint)
    if get_resp.is_error or not isinstance(get_resp.data, dict):
        raise RuntimeError(f"GET workout {workout_id} failed: {getattr(get_resp, 'message', 'not found')}")
    existing = get_resp.data
    if not is_inflated_power_run(existing):
        return {"workoutId": workout_id, "skipped": True, "reason": f"tssSource={existing.get('tssSource')}"}
    payload = apply_rtss_to_workout_payload(existing, new_tss=new_tss, new_if=new_if)
    put_resp = await client.put(endpoint, json=payload)
    if put_resp.is_error:
        raise RuntimeError(f"PUT workout {workout_id} failed: {put_resp.message}")
    return {
        "workoutId": workout_id,
        "skipped": False,
        "old_tss": existing.get("tssActual"),
        "new_tss": new_tss,
        "new_if": new_if,
    }


async def verify_canary_workout(
    client: Any,
    athlete_id: Any,
    workout: dict[str, Any],
    *,
    new_tss: float,
    new_if: float,
) -> dict[str, Any]:
    """Updates 1 workout and verifies BOTH `GET /workouts/{id}` and `POST /reporting/performancedata` reflect it."""
    wid = int(workout["workoutId"])
    day = str(workout.get("workoutDay") or "")[:10]
    old_tss = float(workout.get("tssActual") or 0.0)

    pmc_endpoint = f"/fitness/v1/athletes/{athlete_id}/reporting/performancedata/{day}/{day}"
    pmc_body = {"atlConstant": 7, "atlStart": 0, "ctlConstant": 42, "ctlStart": 0, "workoutTypes": []}

    pmc_before = await client.post(pmc_endpoint, json=pmc_body)
    before_day_tss = float((pmc_before.data or [{}])[0].get("tssActual") or 0.0) if not pmc_before.is_error else None

    update_res = await _update_single_workout(client, athlete_id, wid, new_tss=new_tss, new_if=new_if)

    # Re-read workout and PMC day to confirm TP persisted the update server-side.
    get_after = await client.get(f"/fitness/v6/athletes/{athlete_id}/workouts/{wid}")
    if get_after.is_error or not isinstance(get_after.data, dict):
        raise RuntimeError(f"Canary verification GET failed for {wid}: {getattr(get_after, 'message', '')}")
    persisted_tss = float(get_after.data.get("tssActual") or 0.0)
    persisted_src = get_after.data.get("tssSource")

    pmc_after = await client.post(pmc_endpoint, json=pmc_body)
    after_day_tss = float((pmc_after.data or [{}])[0].get("tssActual") or 0.0) if not pmc_after.is_error else None

    tss_ok = abs(persisted_tss - new_tss) <= 0.5
    pmc_ok = (
        before_day_tss is None
        or after_day_tss is None
        or abs((before_day_tss - after_day_tss) - (old_tss - new_tss)) <= 1.0
    )
    return {
        "workoutId": wid,
        "date": day,
        "title": workout.get("title"),
        "old_tss": old_tss,
        "expected_tss": new_tss,
        "persisted_tss": persisted_tss,
        "persisted_tss_source": persisted_src,
        "pmc_day_tss_before": before_day_tss,
        "pmc_day_tss_after": after_day_tss,
        "verified": bool(tss_ok and pmc_ok and not update_res.get("skipped")),
    }


async def rollback_from_backup(
    client: Any,
    athlete_id: Any,
    backup_path: Path,
    *,
    delay_seconds: float = 0.2,
) -> dict[str, int]:
    """Restores original `tssActual`, `if`, `tssSource`, and `normalizedPowerActual` from a JSON backup."""
    records = json.loads(backup_path.read_text(encoding="utf-8"))
    restored = 0
    failed = 0
    for idx, rec in enumerate(records):
        wid = int(rec["workoutId"])
        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{wid}"
        get_resp = await client.get(endpoint)
        if get_resp.is_error or not isinstance(get_resp.data, dict):
            logger.error("Rollback GET failed for %d: %s", wid, getattr(get_resp, "message", ""))
            failed += 1
            continue
        payload = dict(get_resp.data)
        payload["tssActual"] = rec["tssActual"]
        payload["if"] = rec["if"]
        payload["tssSource"] = rec["tssSource"]
        payload["normalizedPowerActual"] = rec["normalizedPowerActual"]
        put_resp = await client.put(endpoint, json=payload)
        if put_resp.is_error:
            logger.error("Rollback PUT failed for %d: %s", wid, put_resp.message)
            failed += 1
        else:
            restored += 1
        if delay_seconds > 0 and idx + 1 < len(records):
            await asyncio.sleep(delay_seconds)
    return {"restored": restored, "failed": failed}


async def run_fix(
    *,
    client: Any,
    athlete_id: Any,
    start_date: date,
    end_date: date,
    mode: str,
    single_pace: Optional[str] = None,
    delay_seconds: float = 0.2,
    backup_path: Optional[Path] = None,
    remove_backup: bool = False,
) -> dict[str, Any]:
    """Executes dry-run, single-workout canary, or full fix across `[start_date, end_date]`."""
    targets = await discover_target_workouts(client, athlete_id, start_date=start_date, end_date=end_date)
    plan_rows = []
    for w in targets:
        new_tss, new_if, spd = compute_rtss(w, single_pace=single_pace)
        plan_rows.append({
            "workout": w,
            "workoutId": int(w["workoutId"]),
            "date": str(w.get("workoutDay") or "")[:10],
            "title": w.get("title"),
            "old_tss": round(float(w.get("tssActual") or 0.0), 2),
            "new_tss": new_tss,
            "new_if": new_if,
            "speed_ms": spd,
        })

    if mode == "dry-run" or not plan_rows:
        return {
            "mode": mode,
            "count": len(plan_rows),
            "sample": [
                {k: v for k, v in r.items() if k != "workout"}
                for r in (plan_rows[:5] + plan_rows[-3:] if len(plan_rows) > 8 else plan_rows)
            ],
        }

    # Always write full backup before any mutation.
    if backup_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = Path(f"/tmp/tp_tss_backup_{ts}.json")
    snapshots = [snapshot_original_fields(r["workout"]) for r in plan_rows]
    backup_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    logger.info("Saved backup of %d original workouts to %s", len(snapshots), backup_path)

    # Canary check on the first target workout.
    first = plan_rows[0]
    canary = await verify_canary_workout(
        client,
        athlete_id,
        first["workout"],
        new_tss=first["new_tss"],
        new_if=first["new_if"],
    )
    logger.info("Canary result: %s", canary)
    if not canary["verified"]:
        raise RuntimeError(
            f"Canary check failed on workout {first['workoutId']} ({first['date']}): {canary}. "
            f"Aborting before updating remaining workouts. Backup saved at {backup_path}."
        )

    if mode == "test-one":
        return {
            "mode": "test-one",
            "count": len(plan_rows),
            "backup_path": str(backup_path),
            "canary": canary,
        }

    updated = 1
    skipped = 0
    failed: list[dict[str, Any]] = []
    for idx, row in enumerate(plan_rows[1:], start=2):
        try:
            res = await _update_single_workout(
                client,
                athlete_id,
                row["workoutId"],
                new_tss=row["new_tss"],
                new_if=row["new_if"],
            )
            if res.get("skipped"):
                skipped += 1
            else:
                updated += 1
        except Exception as exc:
            logger.error("Failed workout %d (%s): %s", row["workoutId"], row["date"], exc)
            failed.append({"workoutId": row["workoutId"], "date": row["date"], "error": str(exc)})
        if idx % 50 == 0 or idx == len(plan_rows):
            logger.info("Progress: %d/%d (updated=%d skipped=%d failed=%d)", idx, len(plan_rows), updated, skipped, len(failed))
        if delay_seconds > 0 and idx < len(plan_rows):
            await asyncio.sleep(delay_seconds)

    backup_removed = False
    if remove_backup and not failed and backup_path.exists():
        backup_path.unlink()
        backup_removed = True
        logger.info("Removed temporary backup %s after clean completion.", backup_path)

    return {
        "mode": "apply",
        "total_targets": len(plan_rows),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "canary": canary,
        "backup_path": None if backup_removed else str(backup_path),
        "backup_removed": backup_removed,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-time script to fix inflated historical TrainingPeaks running TSS (tssSource 1 -> 2)."
    )
    p.add_argument("--runner-id", default="cyrille_visser", help="Firestore runner ID for TP cookie lookup")
    p.add_argument("--start-date", default="2023-05-01", help="Start date YYYY-MM-DD (default: 2023-05-01)")
    p.add_argument("--end-date", default="2025-10-01", help="End date YYYY-MM-DD (default: 2025-10-01)")
    p.add_argument("--threshold-pace", default=None, help="Optional single threshold pace M:SS (overrides per-year Option A defaults)")
    p.add_argument("--delay-seconds", type=float, default=0.2, help="Pause between PUT calls (default: 0.2s)")
    p.add_argument("--remove-backup", action="store_true", help="Delete the /tmp JSON backup file automatically if all updates succeed")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="List matching workouts without writing anything")
    group.add_argument("--test-one", action="store_true", help="Run canary verification on 1 workout only")
    group.add_argument("--apply", action="store_true", help="Run canary check then update all matching workouts")
    group.add_argument("--rollback", metavar="BACKUP_JSON", help="Restore original values from a backup JSON file")
    return p


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    if not os.getenv("TP_AUTH_COOKIE"):
        cookie = await credentials.get_runner_tp_cookie(args.runner_id)
        if not cookie:
            raise RuntimeError(f"No TrainingPeaks cookie found for '{args.runner_id}'.")
        os.environ["TP_AUTH_COOKIE"] = cookie

    from tp_mcp.client import TPClient

    async with TPClient() as client:
        aid = await client.ensure_athlete_id()
        if not aid:
            raise RuntimeError("Could not resolve TrainingPeaks athlete ID.")
        if args.rollback:
            return await rollback_from_backup(
                client, aid, Path(args.rollback), delay_seconds=args.delay_seconds
            )
        mode = "dry-run" if args.dry_run else ("test-one" if args.test_one else "apply")
        return await run_fix(
            client=client,
            athlete_id=aid,
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            mode=mode,
            single_pace=args.threshold_pace,
            delay_seconds=args.delay_seconds,
            remove_backup=args.remove_backup,
        )


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    result = asyncio.run(_async_main(args))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
