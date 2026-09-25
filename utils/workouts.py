from datetime import date
from typing import Any, Optional
from .classification import BIKE_SPORTS, NON_TRAINING_SPORTS, RUN_SPORTS, STRENGTH_SPORTS
from .date_helpers import parse_date, parse_iso_timestamp
from .metrics import as_float, pace_seconds, to_km

# Lap NGP is only shown next to raw pace when they differ by at least this much.
NGP_MIN_DIFF_S = 3.0

# "No value" placeholders TrainingPeaks sends instead of a number (e.g. VAM '--').
_PLACEHOLDERS = {"", "-", "--", "n/a", "na", "null", "none"}


def _clean(value: Any) -> Optional[Any]:
    """Returns the raw value for display, or None when it is missing or a placeholder."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _PLACEHOLDERS:
        return None
    return value


def _is_positive(value: Any) -> bool:
    """True when a raw MCP value represents a number greater than zero."""
    if isinstance(value, bool) or value is None:
        return False
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


# Fields that, when positive, prove a session was actually executed.
_ACTUALS_FIELDS = (
    "distance_actual_km",
    "tss_actual",
    "duration_actual",
)


def is_workout_completed(workout: dict) -> bool:
    """Canonical check for whether a workout has been executed/completed."""
    if not workout:
        return False
    if workout.get("type") == "completed":
        return True
    return any(_is_positive(workout.get(field)) for field in _ACTUALS_FIELDS)


def partition_workouts_by_date(
    workouts_list: list[dict],
    reference_date: date,
) -> tuple[list[dict], Optional[list[dict]]]:
    """Splits workouts into (completed/past, upcoming).

    A session on the reference date counts as past only once it is completed.
    The upcoming list is None when empty so callers can omit the section entirely.
    """
    past_list: list[dict] = []
    future_list: list[dict] = []

    for w in workouts_list or []:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date:
            continue
        if w_date < reference_date or (w_date == reference_date and is_workout_completed(w)):
            past_list.append(w)
        else:
            future_list.append(w)

    return past_list, (future_list or None)


# Sport priority when picking a day's primary session (lower = more important).
_SPORT_TIERS = ((RUN_SPORTS, 0), (BIKE_SPORTS, 1), (STRENGTH_SPORTS, 3))
_OTHER_ENDURANCE_TIER = 2  # swim, row, ...
_NON_TRAINING_TIER = 4
_NON_TRAINING = {s.lower() for s in NON_TRAINING_SPORTS}
_SPORT_FAMILIES = {"run": RUN_SPORTS, "bike": BIKE_SPORTS}


def _sport_key(workout: dict) -> str:
    return (workout.get("sport") or "").strip().lower()


def _sport_tier(workout: dict) -> int:
    sport = _sport_key(workout)
    if sport in _NON_TRAINING:
        return _NON_TRAINING_TIER
    for sports, tier in _SPORT_TIERS:
        if sport in sports:
            return tier
    return _OTHER_ENDURANCE_TIER


def _start_ordinal(workout: dict) -> float:
    ts = parse_iso_timestamp(workout.get("start_time") or workout.get("date"))
    return ts.timestamp() if ts else 0.0


def select_primary_workout(
    completed: list[dict], sport: Optional[str] = None
) -> tuple[Optional[dict], list[dict]]:
    """Returns (primary, others) for a day's completed workouts.

    `sport` ('run' / 'bike') restricts the choice to that family when one exists.
    Ranking: sport tier (run > bike > other endurance > strength > non-training),
    then highest actual TSS, longest duration, latest start.
    """
    if not completed:
        return None, []
    family = _SPORT_FAMILIES.get((sport or "").strip().lower())
    pool = [w for w in completed if family and _sport_key(w) in family] or completed
    primary = min(pool, key=lambda w: (
        _sport_tier(w),
        -(as_float(w.get("tss_actual")) or 0.0),
        -(as_float(w.get("duration_actual")) or 0.0),
        -_start_ordinal(w),
    ))
    return primary, [w for w in completed if w is not primary]


def format_other_sessions(others: list[dict], date_iso: str) -> str:
    """One-line disclosure of the day's other completed sessions, or '' when none."""
    items = []
    for w in others or []:
        details = [w.get("sport") or "Workout"]
        hours = as_float(w.get("duration_actual"))
        if hours:
            details.append(f"{round(hours * 60)} min")
        tss = as_float(w.get("tss_actual"))
        if tss is not None:
            details.append(f"TSS {round(tss, 1)}")
        details.append(f"id {w.get('id')}")
        items.append(f"'{w.get('title') or w.get('sport') or 'Workout'}' ({', '.join(details)})")
    if not items:
        return ""
    return (
        f"Other completed sessions on {date_iso} (not analysed): {'; '.join(items)}. "
        "Call analyze_workout(workout_id=...) to analyse one."
    )



ALLOWED_DATA_CHANNELS = {
    "HeartRate", "Pace", "Power", "Cadence", "Speed", "Torque",
    "GroundContactTime", "ContactTime", "GCT", "StanceTime",
    "GroundContactTimeBalance", "GCTBalance", "ContactTimeBalance", "Balance",
    "VerticalOscillation", "VertOsc",
    "StrideLength", "StepLength",
    "VerticalRatio",
    "Altitude", "Elevation", "Grade", "VAM",
}

def _get_metric_val(totals: dict, *keys: str) -> Optional[Any]:
    """Extracts a metric value from totals dictionary supporting objects {value, unit} or direct scalars."""
    for k in keys:
        if k in totals:
            val = totals[k]
            if isinstance(val, dict):
                return val.get("value")
            return val
    for k in keys:
        for tk, tv in totals.items():
            if tk.lower() == k.lower():
                if isinstance(tv, dict):
                    return tv.get("value")
                return tv
    return None


def _get_metric_unit(totals: dict, *keys: str) -> Optional[str]:
    """Returns the unit of the first matching {value, unit} totals entry, if any."""
    for k in keys:
        val = totals.get(k)
        if isinstance(val, dict):
            return val.get("unit")
    return None

def _format_pace(pace_val: Any) -> str:
    """Formats pace given in seconds per km (or decimal min per km) into M:SS/km format."""
    secs = pace_seconds(pace_val)
    if secs is None:
        return ""
    total = int(round(secs))
    return f"{total // 60}:{total % 60:02d}/km"

def _format_duration(dur_seconds: Any) -> str:
    """Formats duration seconds into human-readable hours, minutes, and seconds."""
    if dur_seconds is None:
        return ""
    try:
        s_total = float(dur_seconds)
        if s_total <= 0:
            return ""
        hours = int(s_total // 3600)
        rem = s_total % 3600
        mins = int(rem // 60)
        secs = int(round(rem % 60))
        if hours > 0:
            return f"{hours}h {mins:02d}m {secs:02d}s" if secs else f"{hours}h {mins:02d}m"
        return f"{mins}m {secs:02d}s" if secs else f"{mins}m"
    except (ValueError, TypeError):
        return str(dur_seconds)

def format_workout_analysis(
    data: Optional[dict],
    title: Optional[str] = None,
    sport: Optional[str] = None,
    include_laps: bool = True,
    decoupling_override: Optional[str] = None,
) -> str:
    """Sanitizes and formats raw TrainingPeaks workout analysis directly into a token-efficient text summary.

    decoupling_override: pre-computed windowed Pa:Hr/Pw:Hr line (first minutes and warm-up/cool-down
    excluded). It replaces TP's whole-session values; '' omits them (window too short); None keeps
    TP's values, labelled as whole-session.
    include_laps: False when a structured-execution section already covers the laps.
    """
    if not data or not isinstance(data, dict):
        return "No analysis data returned."

    w_id = data.get("workoutId", "")
    totals = data.get("totals", {})
    channels = data.get("dataChannels", [])
    laps = data.get("lapData", [])

    header_parts = [f"[{w_id}]"]
    if title:
        header_parts.append(title)
    if sport and sport.lower() not in (title or "").lower():
        header_parts.append(f"({sport})")
    lines = [f"### Workout Analysis {' '.join(header_parts)}"]

    if totals:
        # Distance
        dist_val = _get_metric_val(totals, "Distance", "distance", "TotalDistance")
        dist_km = to_km(dist_val, _get_metric_unit(totals, "Distance", "distance", "TotalDistance"))
        dist_str = f"Distance: {round(dist_km, 2)}km" if dist_km is not None else ""

        # Duration
        dur_val = _clean(_get_metric_val(totals, "Duration", "duration", "Moving time", "Moving Time", "Elapsed time"))
        dur_str = ""
        if dur_val is not None:
            dur_str = f"Duration: {_format_duration(dur_val)}"

        # Pace: graded (NGP) when available, otherwise the raw average
        ngp_val = _get_metric_val(totals, "NGP", "NormalizedGradedPace")
        avg_pace_val = _get_metric_val(totals, "Pace", "AveragePace")
        if ngp_val:
            pace_str = f"NGP: {_format_pace(ngp_val)}"
        elif avg_pace_val:
            pace_str = f"Avg Pace: {_format_pace(avg_pace_val)}"
        else:
            pace_str = ""

        # Mechanical work (bike power meters)
        energy_val = as_float(_get_metric_val(totals, "Energy", "Work", "TotalWork"))
        energy_str = f"Work: {round(energy_val)}kJ" if energy_val is not None and energy_val > 0 else ""

        # TSS
        rtss = as_float(_get_metric_val(totals, "rTSS", "rTss"))
        tss = as_float(_get_metric_val(totals, "TSS", "tss"))
        hrtss = as_float(_get_metric_val(totals, "hrTSS", "hrTss"))
        tss_parts = []
        if rtss is not None:
            tss_parts.append(f"rTSS: {round(rtss, 1)}")
        if tss is not None and tss != rtss:
            tss_parts.append(f"TSS: {round(tss, 1)}")
        if hrtss is not None:
            tss_parts.append(f"hrTSS: {round(hrtss, 1)}")
        tss_str = " | ".join(tss_parts)

        # Intensity Factor (IF)
        rif = as_float(_get_metric_val(totals, "rIF", "rIf"))
        if_val = as_float(_get_metric_val(totals, "IF", "intensityFactor"))
        if_str = ""
        if rif is not None:
            if_str = f"rIF: {round(rif, 2)}"
        elif if_val is not None:
            if_str = f"IF: {round(if_val, 2)}"

        # Normalized Power (NP)
        np_val = as_float(_get_metric_val(totals, "NP", "NormalizedPower"))
        np_str = f"NP: {round(np_val, 0)}W" if np_val is not None else ""

        # Decoupling & Efficiency
        pahr = _clean(_get_metric_val(totals, "Pa:Hr", "PaHr", "PacePulseDecoupling"))
        pwhr = _clean(_get_metric_val(totals, "Pw:Hr", "PwHr", "PowerPulseDecoupling"))
        ef = _clean(_get_metric_val(totals, "EF", "EfficiencyFactor"))
        decoup_parts = []
        if decoupling_override is not None:
            if decoupling_override:
                decoup_parts.append(decoupling_override)
        else:
            if pahr is not None:
                decoup_parts.append(f"Pa:Hr (whole session, incl. warm-up): {pahr}%")
            if pwhr is not None:
                decoup_parts.append(f"Pw:Hr (whole session, incl. warm-up): {pwhr}%")
        if ef is not None:
            decoup_parts.append(f"EF: {ef}")
        decoup_str = " | ".join(decoup_parts)

        # Elevation Gain & Loss
        el_gain = _clean(_get_metric_val(totals, "El. Gain", "ElevationGain", "TotalAscent"))
        el_loss = _clean(_get_metric_val(totals, "El. Loss", "ElevationLoss", "TotalDescent"))
        el_str = ""
        if el_gain is not None or el_loss is not None:
            g = f"+{el_gain}m" if el_gain is not None else ""
            l = f"-{el_loss}m" if el_loss is not None else ""
            el_str = f"Elevation: {' / '.join(filter(None, [g, l]))}"

        # Vertical Ascent Rate (VAM) & Average Grade
        vam_val = as_float(_get_metric_val(totals, "VAM", "AverageVam"))
        vam_str = f"VAM: {int(round(vam_val))}m/h" if (vam_val is not None and vam_val > 0) else ""

        grade_val = as_float(_get_metric_val(totals, "Grade", "AverageGrade"))
        grade_str = f"Grade: {round(grade_val, 1)}%" if (grade_val is not None and grade_val != 0) else ""

        summary_parts = [p for p in [dist_str, dur_str, pace_str, tss_str, if_str, np_str, energy_str, decoup_str, el_str, vam_str, grade_str] if p]
        if summary_parts:
            lines.append("Totals: " + " | ".join(summary_parts))

    if isinstance(channels, list) and channels:
        ch_items = []
        for ch in channels:
            if isinstance(ch, dict) and ch.get("identifier") in ALLOWED_DATA_CHANNELS:
                name = ch.get("name") or ch.get("identifier")
                unit = ch.get("unit", "")
                avg_val = _clean(ch.get("average"))
                min_val = _clean(ch.get("min"))
                max_val = _clean(ch.get("max"))
                if avg_val is not None:
                    if name == "Power" and unit == "watts":
                        unit = "W"
                    elif name == "Pace" and unit == "min/km":
                        avg_val_str = _format_pace(avg_val)
                        ch_items.append(f"{name}: Avg {avg_val_str}")
                        continue
                    elif name in ("Elevation", "Altitude") and unit == "m":
                        range_str = f" (Min {min_val}m, Max {max_val}m)" if (min_val is not None and max_val is not None) else ""
                        ch_items.append(f"Elevation: Avg {avg_val}m{range_str}")
                        continue

                    max_str = f" (Max {max_val}{unit})" if max_val is not None else ""
                    ch_items.append(f"{name}: Avg {avg_val}{unit}{max_str}")
        if ch_items:
            lines.append("Channels: " + " | ".join(ch_items))

    if include_laps and isinstance(laps, list) and laps:
        is_bike = (sport or "").strip().lower() in BIKE_SPORTS
        lines.append("Laps Breakdown:")
        for idx, lap in enumerate(laps, start=1):
            if not isinstance(lap, dict):
                continue
            l_num = lap.get("Name") or lap.get("lapNumber") or lap.get("lapIndex") or f"Lap {idx}"
            if not str(l_num).lower().startswith("lap"):
                l_num = f"Lap {l_num}"

            dur_s = as_float(lap.get("TotalTimerTime", lap.get("TotalMovingTime", lap.get("TotalElapsedTime", lap.get("duration_seconds", lap.get("duration", 0))))))
            dur_str = f"{round(dur_s / 60.0, 1)}m" if dur_s else ""

            # Lap Distance
            lap_km = to_km(lap.get("TotalDistance", lap.get("distance_km", lap.get("Distance", lap.get("distance")))))
            dist_str = f"{round(lap_km, 2)}km" if lap_km else ""

            avg_hr = _clean(lap.get("AverageHeartRate"))
            max_hr = _clean(lap.get("MaximumHeartRate"))
            hr_str = f"HR {avg_hr}/{max_hr}bpm" if (avg_hr and max_hr) else f"HR {avg_hr}bpm" if avg_hr else ""

            # Pace & Lap NGP comparison (NGP shown only when it differs noticeably)
            raw_s = pace_seconds(lap.get("AveragePace"))
            ngp_s = pace_seconds(lap.get("NormalizedGradedPace"))
            pace_str = ""
            if raw_s is not None:
                pace_str = f"Pace {_format_pace(raw_s)}"
                if ngp_s is not None and abs(raw_s - ngp_s) >= NGP_MIN_DIFF_S:
                    pace_str += f" (NGP {_format_pace(ngp_s)})"
            elif ngp_s is not None:
                pace_str = f"NGP {_format_pace(ngp_s)}"

            # Lap Elevation & Grade
            ascent = lap.get("TotalAscent")
            descent = lap.get("TotalDescent")
            ascent_n = as_float(ascent) or 0.0
            descent_n = as_float(descent) or 0.0
            lap_el_str = ""
            if ascent_n > 0 or descent_n > 0:
                g_str = f"+{ascent}m" if ascent_n else "+0m"
                d_str = f"-{descent}m" if descent_n else "-0m"
                lap_el_str = f"Elev {g_str}/{d_str}"

            lap_grade = lap.get("AverageGrade")
            lap_grade_n = as_float(lap_grade)
            grade_str = f"Grade {lap_grade}%" if (lap_grade_n is not None and lap_grade_n != 0) else ""

            lap_vam = as_float(lap.get("AverageVam"))
            lap_vam_str = f"VAM {int(round(lap_vam))}m/h" if (lap_vam is not None and lap_vam >= 50) else ""

            pwr = _clean(lap.get("AveragePower")) or _clean(lap.get("NormalizedPower"))
            pwr_str = f"Pwr {pwr}W" if pwr else ""

            cad = _clean(lap.get("AverageCadence"))
            cad_str = f"Cad {cad}{'rpm' if is_bike else 'spm'}" if cad else ""

            pw_hr = _clean(lap.get("PowerPulseDecoupling"))
            pa_hr = _clean(lap.get("PacePulseDecoupling"))
            if is_bike and pw_hr is not None:
                decoup_str = f"Pw:Hr {pw_hr}%"
            elif pa_hr is not None:
                decoup_str = f"Pa:Hr {pa_hr}%"
            elif pw_hr is not None:
                decoup_str = f"Pw:Hr {pw_hr}%"
            else:
                decoup_str = ""

            # Running Dynamics (POD 2 / Stryd / Garmin RD)
            gct = _clean(lap.get("AverageStanceTime") or lap.get("AverageGroundContactTime") or lap.get("groundContactTime") or lap.get("ContactTime") or lap.get("gct"))
            gct_str = f"GCT {round(gct, 1)}ms" if isinstance(gct, (int, float)) else f"GCT {gct}" if gct else ""

            bal = _clean(lap.get("AverageGroundContactTimeBalance") or lap.get("groundContactTimeBalance") or lap.get("gctBalance"))
            bal_str = f"Bal {bal}" if bal else ""

            vert = _clean(lap.get("AverageVerticalOscillation") or lap.get("verticalOscillation") or lap.get("vertOsc"))
            vert_str = ""
            if vert is not None:
                if isinstance(vert, (int, float)):
                    v_cm = vert / 10.0 if vert > 20 else vert
                    vert_str = f"Vert {round(v_cm, 1)}cm"
                else:
                    vert_str = f"Vert {vert}"

            stride = _clean(lap.get("AverageStepLength") or lap.get("AverageStrideLength") or lap.get("strideLength") or lap.get("stepLength"))
            stride_str = ""
            if stride is not None:
                if isinstance(stride, (int, float)):
                    s_m = stride / 1000.0 if stride > 20 else stride
                    stride_str = f"Stride {round(s_m, 2)}m"
                else:
                    stride_str = f"Stride {stride}"

            lap_parts = [p for p in [dist_str, dur_str, pace_str, lap_el_str, grade_str, lap_vam_str, hr_str, pwr_str, cad_str, decoup_str, gct_str, bal_str, vert_str, stride_str] if p]
            lines.append(f"- {l_num}: " + " | ".join(lap_parts))

    return "\n".join(lines)
