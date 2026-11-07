"""Structured workout-analysis web report payload (`workout_report_data`) for the session banner.

The web UI renders the session overview (headline metrics, elevation profile, HR-zone split,
conditions and readiness) from this payload; the coach's markdown keeps the judgement.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Optional

from ....shared.athlete_settings import sport_family
from ....shared.units import as_float, pace_seconds, to_km
from ....shared.web_report_payload import REPORT_DATA_VERSION, iso_or_none, round_or_none
from ....shared.workout_structure import pa_hr_window, series_end, windowed_decoupling
from .workout_summary_text import _clean, _get_metric_unit, _get_metric_val

WORKOUT_REPORT_STATE_KEY = "workout_report_data"

MAX_TILES = 6
ELEVATION_POINTS = 60
# Gaps longer than this (pauses, GPS drop-outs) count only this long towards time in zone.
MAX_ZONE_STEP_S = 30.0
MIN_ZONE_TOTAL_S = 60.0
# The banner names the profile's home location only when the run started near it.
HOME_RADIUS_KM = 30.0
# Readiness: a change smaller than this vs the preceding days' mean reads as flat.
HRV_FLAT_PCT = 5.0
RHR_FLAT_BPM = 2.0


def _clock(seconds: Optional[float]) -> Optional[str]:
    """H:MM:SS (>= 1h) or M:SS; None when missing."""
    if seconds is None or seconds <= 0:
        return None
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _pace(value: Any) -> Optional[str]:
    secs = pace_seconds(value)
    if secs is None:
        return None
    total = int(round(secs))
    return f"{total // 60}:{total % 60:02d}"


def _num(value: Any, digits: int = 0) -> Optional[str]:
    v = as_float(_clean(value))
    if v is None:
        return None
    return f"{v:.{digits}f}" if digits else str(int(round(v)))


def _channel(data: dict, identifier: str, field: str) -> Optional[float]:
    for ch in data.get("dataChannels") or []:
        if isinstance(ch, dict) and str(ch.get("identifier") or ch.get("name") or "").replace(" ", "") == identifier:
            return as_float(ch.get(field))
    return None


def _tile(key: str, label: str, value: Optional[str], unit: str = "", sub: Optional[str] = None) -> Optional[dict]:
    if not value:
        return None
    return {"key": key, "label": label, "value": value, "unit": unit, "sub": sub}


def _tiles(data: dict, meta_metrics: dict, sport: Optional[str], decoupling: Optional[float]) -> list[dict]:
    """Headline metrics, sport-aware, in display order; missing values are skipped."""
    totals = data.get("totals") or {}
    if not isinstance(totals, dict):
        totals = {}
    family = sport_family(sport)

    dist_keys = ("Distance", "distance", "TotalDistance")
    dist_km = to_km(_get_metric_val(totals, *dist_keys), _get_metric_unit(totals, *dist_keys))
    if dist_km is None:
        dist_km = as_float(meta_metrics.get("distance_actual_km"))
    duration = as_float(_clean(_get_metric_val(totals, "Duration", "duration", "Moving time", "Moving Time", "Elapsed time")))
    if duration is None and as_float(meta_metrics.get("duration_actual")):
        duration = as_float(meta_metrics.get("duration_actual")) * 3600.0

    hr_avg = as_float(_clean(_get_metric_val(totals, "Avg heart rate", "AverageHeartRate"))) or _channel(data, "HeartRate", "average")
    if hr_avg is None:
        hr_avg = as_float(meta_metrics.get("avg_hr"))
    hr_max = as_float(_clean(_get_metric_val(totals, "Max heart rate", "MaximumHeartRate"))) or _channel(data, "HeartRate", "max")
    cadence = _channel(data, "Cadence", "average") or as_float(meta_metrics.get("avg_cadence"))

    # Load: run prefers rTSS, then TSS / hrTSS; bike uses TSS; the workout's own TSS is the fallback.
    tss_options = [("TSS", as_float(_get_metric_val(totals, "TSS")))] if family == "bike" else [
        ("rTSS", as_float(_get_metric_val(totals, "rTSS", "rTss"))),
        ("TSS", as_float(_get_metric_val(totals, "TSS"))),
        ("hrTSS", as_float(_get_metric_val(totals, "hrTSS", "hrTss"))),
    ]
    tss_options.append(("TSS", as_float(meta_metrics.get("tss_actual"))))
    tss_kind, tss = next(((k, v) for k, v in tss_options if v is not None), ("TSS", None))

    common = [
        _tile("distance", "Distance", f"{dist_km:.1f}" if dist_km else None, "km"),
        _tile("duration", "Duration", _clock(duration)),
    ]
    hr_tile = _tile("hr", "Avg HR", _num(hr_avg), "bpm", f"max {int(round(hr_max))}" if hr_max else None)
    tss_tile = _tile("tss", tss_kind, _num(tss))
    dec_tile = _tile(
        "decoupling", "Pw:Hr" if family == "bike" else "Pa:Hr",
        f"{decoupling:.1f}" if decoupling is not None else None, "%",
    )
    cad_tile = _tile("cadence", "Cadence", _num(cadence), "rpm" if family == "bike" else "spm")

    if family == "bike":
        np_w = as_float(_get_metric_val(totals, "NP", "NormalizedPower")) or as_float(meta_metrics.get("normalized_power"))
        avg_w = _channel(data, "Power", "average") or as_float(meta_metrics.get("avg_power"))
        power = _tile("power", "NP", _num(np_w), "W") or _tile("power", "Avg power", _num(avg_w), "W")
        if_val = as_float(_get_metric_val(totals, "IF", "intensityFactor")) or as_float(meta_metrics.get("if_actual"))
        ordered = [*common, power, hr_tile, tss_tile, _tile("if", "IF", f"{if_val:.2f}" if if_val else None),
                   dec_tile, cad_tile]
    else:
        ngp = _pace(_get_metric_val(totals, "NGP", "NormalizedGradedPace"))
        avg = _pace(_get_metric_val(totals, "Pace", "AveragePace"))
        pace = _tile("pace", "NGP", ngp, "/km") or _tile("pace", "Avg pace", avg, "/km")
        ordered = [*common, pace, hr_tile, tss_tile, dec_tile, cad_tile]
    return [t for t in ordered if t][:MAX_TILES]


def _decoupling(series: Optional[list[dict]], laps: list[dict], sport: Optional[str], alignment: Any) -> Optional[float]:
    """The same windowed Pa:Hr / Pw:Hr value the coach sees (first minutes and warm-up/cool-down excluded)."""
    if not series and not laps:
        return None
    window = pa_hr_window(series_end(series, laps), alignment)
    return windowed_decoupling(series, laps, *window, sport)[0] if window else None


def _elevation(data: dict, series: Optional[list[dict]]) -> Optional[dict]:
    """Gain/loss from TP totals and a downsampled [[km, m], ...] profile from the telemetry."""
    totals = data.get("totals") or {}
    gain = round_or_none(_clean(_get_metric_val(totals, "El. Gain", "ElevationGain", "TotalAscent")), 0) if isinstance(totals, dict) else None
    loss = round_or_none(_clean(_get_metric_val(totals, "El. Loss", "ElevationLoss", "TotalDescent")), 0) if isinstance(totals, dict) else None

    pts = []
    for p in series or []:
        alt = as_float(p.get("SmoothedAltitude"))
        if alt is None:
            alt = as_float(p.get("Altitude"))
        x = as_float(p.get("Distance"))
        if alt is not None and x is not None:
            pts.append((x, alt))
    profile = None
    if len(pts) >= 10 and pts[-1][0] > pts[0][0]:
        x0, x1 = pts[0][0], pts[-1][0]
        width = (x1 - x0) / ELEVATION_POINTS
        buckets: list[list[float]] = [[] for _ in range(ELEVATION_POINTS)]
        for x, alt in pts:
            buckets[min(int((x - x0) / width), ELEVATION_POINTS - 1)].append(alt)
        profile = [
            [round(x0 + (i + 0.5) * width, 2), round(sum(b) / len(b), 1)]
            for i, b in enumerate(buckets) if b
        ]
    if gain is None and loss is None and not profile:
        return None
    return {"gain_m": gain, "loss_m": loss, "profile": profile}


def _hr_zones(series: Optional[list[dict]], zones: list[dict]) -> Optional[list[dict]]:
    """Share of moving time per athlete HR zone from the telemetry; None without HR data or zones."""
    if not series or not zones:
        return None
    pts = [(as_float(p.get("time")), as_float(p.get("HeartRate"))) for p in series]
    pts = [(t, hr) for t, hr in pts if t is not None and hr and hr > 0]
    seconds = [0.0] * len(zones)
    for (t, hr), (t_next, _) in zip(pts, pts[1:]):
        dt = min(max(t_next - t, 0.0), MAX_ZONE_STEP_S)
        idx = next((i for i, z in enumerate(zones) if z.get("max") is not None and hr <= z["max"]), len(zones) - 1)
        seconds[idx] += dt
    total = sum(seconds)
    if total < MIN_ZONE_TOTAL_S:
        return None
    return [
        {"label": f"Z{i + 1}", "name": z.get("label") or f"Zone {i + 1}",
         "pct": round(s / total * 100.0, 1), "seconds": round(s)}
        for i, (z, s) in enumerate(zip(zones, seconds))
    ]


def _direction(delta: float, flat: float) -> str:
    return "flat" if abs(delta) < flat else ("up" if delta > 0 else "down")


def _readiness(dated: Optional[dict], workout_date: date) -> Optional[list[dict]]:
    """Morning HRV / RHR / sleep with direction vs the preceding days' mean."""
    if not dated:
        return None
    out = []
    for key, label, unit in (("hrv", "HRV", "ms"), ("rhr", "RHR", "bpm"), ("sleep", "Sleep", "h")):
        vals = sorted((d, v) for d, v in dated.get(key) or [] if d is not None and d <= workout_date)
        if not vals:
            continue
        latest_day, latest = vals[-1]
        prior = [v for d, v in vals if d < latest_day]
        item: dict[str, Any] = {
            "key": key, "label": label, "unit": unit,
            "value": round(latest, 1) if key == "sleep" else round(latest),
            "date": latest_day.isoformat(), "direction": None, "tone": "slate",
        }
        if prior and key != "sleep":
            base = sum(prior) / len(prior)
            if key == "hrv" and base > 0:
                item["direction"] = _direction((latest - base) / base * 100.0, HRV_FLAT_PCT)
                item["tone"] = {"up": "emerald", "down": "amber"}.get(item["direction"], "slate")
            elif key == "rhr":
                item["direction"] = _direction(latest - base, RHR_FLAT_BPM)
                item["tone"] = {"down": "emerald", "up": "amber"}.get(item["direction"], "slate")
        out.append(item)
    return out or None


def _home_distance_km(profile: dict, position: Optional[dict]) -> Optional[float]:
    lat1, lon1 = as_float(profile.get("latitude")), as_float(profile.get("longitude"))
    lat2 = as_float((position or {}).get("lat"))
    lon2 = as_float((position or {}).get("lon"))
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _location(profile: dict, position: Optional[dict]) -> Optional[str]:
    """Profile home location, unless the GPS start is clearly elsewhere (no reverse geocoding)."""
    home = (profile.get("location") or "").strip() or None
    if not home or not position:
        return home
    dist = _home_distance_km(profile, position)
    return home if dist is not None and dist <= HOME_RADIUS_KM else None


def _local_time(local_start: Optional[str]) -> Optional[str]:
    text = str(local_start or "")
    if "T" not in text:
        return None
    hhmm = text.split("T", 1)[1][:5]
    return hhmm if len(hhmm) == 5 and hhmm != "00:00" else None


def _weather(conditions: Optional[dict]) -> Optional[dict]:
    if not isinstance(conditions, dict):
        return None
    w = {
        "temp_c": round_or_none(conditions.get("temp_c"), 0),
        "feels_like_c": round_or_none(conditions.get("feels_like_c"), 0),
        "humidity": round_or_none(conditions.get("humidity", conditions.get("humidity_pct")), 0),
        "wind_kmh": round_or_none(conditions.get("wind_kmh", conditions.get("wind_kph")), 0),
    }
    return w if any(v is not None for v in w.values()) else None


def workout_report_data(
    data: dict,
    meta: dict,
    *,
    profile: dict,
    sport: Optional[str],
    title: Optional[str],
    workout_date: date,
    local_start: Optional[str],
    series: Optional[list[dict]],
    alignment: Any,
    hr_zones: list[dict],
    weather: Optional[dict],
    dated_metrics: Optional[dict],
    start_position: Optional[dict],
    structured: bool,
    other_sessions: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Structured session-overview payload (`workout_report_data`) stored in session state."""
    laps = data.get("lapData") if isinstance(data.get("lapData"), list) else []
    meta_metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    family = sport_family(sport)
    return {
        "version": REPORT_DATA_VERSION,
        "workout_id": str(data.get("workoutId") or meta.get("id") or ""),
        "title": title or sport or "Workout",
        "sport": sport or "Workout",
        "sport_family": family,
        "date": iso_or_none(workout_date),
        "start_time": _local_time(local_start),
        "location": _location(profile, start_position),
        "structured": bool(structured),
        "tiles": _tiles(data, meta_metrics, sport, _decoupling(series, laps, sport, alignment)),
        "elevation": _elevation(data, series),
        "hr_zones": _hr_zones(series, hr_zones),
        "weather": _weather(weather),
        "readiness": _readiness(dated_metrics, workout_date),
        "other_sessions": [
            {"id": str(s.get("id") or ""), "title": s.get("title") or s.get("sport") or "Workout",
             "sport": s.get("sport") or ""}
            for s in other_sessions or [] if isinstance(s, dict)
        ],
    }
