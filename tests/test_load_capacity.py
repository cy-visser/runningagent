"""Load capacity (utils.load_capacity): proven streaks, tolerance blocking and build outlook."""

from datetime import date, timedelta

from running_coach.utils.load_capacity import build_weeks, capacity_outlook, volume_levels

MONDAY = date(2026, 6, 1)


def _row(i, km, hrv=0.0, rhr=0.0, complete=True):
    return {"week": MONDAY + timedelta(weeks=i), "complete": complete, "km": km, "tss": km * 8,
            "hrv_delta_pct": hrv, "rhr_delta": rhr, "sleep_delta_min": 0.0, "niggle": False,
            "easy_ef": 1.2, "rpe": None}


def test_proven_requires_tolerated_streak_and_ignores_partial_weeks():
    rows = [_row(i, km) for i, km in enumerate([52, 55, 61, 63, 65, 72, 58, 74])] + [_row(8, 95, complete=False)]
    levels = {lv["level"]: lv for lv in volume_levels(rows)}
    assert levels[60]["proven"] and not levels[70]["proven"] and max(levels) == 70

    stressed = [_row(i, 65, hrv=-10, rhr=5) for i in range(4)]
    assert not {lv["level"]: lv for lv in volume_levels(stressed)}[60]["proven"]


def test_capacity_outlook_and_cutback_build_weeks():
    rows = [_row(i, km) for i, km in enumerate([52, 55, 61, 58, 65, 72, 58, 60])]
    o = capacity_outlook(rows, volume_levels(rows))
    status = {t["target"]: t["status"] for t in o["targets"]}
    assert o["proven_km"] == 50 and status[60] == "run, not proven" and status[80] == "untested"
    assert (build_weeks(50, 66), build_weeks(50, 66.6)) == (3, 5)          # week 4 is a cutback
