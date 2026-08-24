from datetime import date
from typing import Any, Optional
from ..utils.date_helpers import parse_date

def is_workout_completed(workout: dict) -> bool:
    """Canonical check for whether a workout has been executed/completed."""
    if not workout:
        return False
    return (
        bool(workout.get("completed"))
        or (workout.get("distance_actual_km") is not None and workout.get("distance_actual_km") > 0)
        or (workout.get("tss_actual") is not None and workout.get("tss_actual") > 0)
        or (workout.get("duration_actual_min") is not None and workout.get("duration_actual_min") > 0)
        or (workout.get("duration_actual") is not None and workout.get("duration_actual") > 0)
        or workout.get("type") == "completed"
    )

def partition_workouts_by_date(
    workouts_list: list[dict],
    reference_date: date,
    has_past: bool = True
) -> tuple[Optional[list[dict]], Optional[list[dict]]]:
    """Partitions a list of workouts into completed past workouts and upcoming future workouts."""
    if not workouts_list:
        return ([], None) if has_past else (None, None)
        
    past_list = []
    future_list = []
    
    for w in workouts_list:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date:
            continue
            
        completed = is_workout_completed(w)
        if w_date < reference_date or (w_date == reference_date and completed):
            past_list.append(w)
        else:
            future_list.append(w)
            
    workouts_past = past_list if (past_list or has_past) else None
    workouts_future = future_list if future_list else None
    
    return workouts_past, workouts_future


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

def _format_pace(pace_val: Any) -> str:
    """Formats pace given in seconds per km (or min per km) into M:SS/km format."""
    if pace_val is None:
        return ""
    try:
        val = float(pace_val)
        if val <= 0:
            return ""
        if val > 30:  # Seconds per km
            m = int(val // 60)
            s = int(round(val % 60))
            if s == 60:
                m += 1
                s = 0
            return f"{m}:{s:02d}/km"
        else:  # Decimal minutes per km
            m = int(val)
            s = int(round((val - m) * 60))
            if s == 60:
                m += 1
                s = 0
            return f"{m}:{s:02d}/km"
    except (ValueError, TypeError):
        return str(pace_val)

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
    sport: Optional[str] = None
) -> str:
    """Sanitizes and formats raw TrainingPeaks workout analysis directly into a token-efficient text summary."""
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
        dist_str = ""
        if dist_val is not None:
            try:
                d = float(dist_val)
                d_km = d / 1000.0 if d > 500 else d
                dist_str = f"Distance: {round(d_km, 2)}km"
            except (ValueError, TypeError):
                dist_str = f"Distance: {dist_val}"

        # Duration
        dur_val = _get_metric_val(totals, "Duration", "duration", "Moving time", "Moving Time", "Elapsed time")
        dur_str = ""
        if dur_val is not None:
            dur_str = f"Duration: {_format_duration(dur_val)}"

        # Pace / NGP / Speed
        ngp_val = _get_metric_val(totals, "NGP", "NormalizedGradedPace", "Pace", "AveragePace")
        pace_str = f"NGP: {_format_pace(ngp_val)}" if ngp_val else ""

        # TSS
        rtss = _get_metric_val(totals, "rTSS", "rTss")
        tss = _get_metric_val(totals, "TSS", "tss")
        hrtss = _get_metric_val(totals, "hrTSS", "hrTss")
        tss_parts = []
        if rtss is not None:
            tss_parts.append(f"rTSS: {round(float(rtss), 1)}")
        if tss is not None and tss != rtss:
            tss_parts.append(f"TSS: {round(float(tss), 1)}")
        if hrtss is not None:
            tss_parts.append(f"hrTSS: {round(float(hrtss), 1)}")
        tss_str = " | ".join(tss_parts)

        # Intensity Factor (IF)
        rif = _get_metric_val(totals, "rIF", "rIf")
        if_val = _get_metric_val(totals, "IF", "intensityFactor")
        if_str = ""
        if rif is not None:
            if_str = f"rIF: {round(float(rif), 2)}"
        elif if_val is not None:
            if_str = f"IF: {round(float(if_val), 2)}"

        # Normalized Power (NP)
        np_val = _get_metric_val(totals, "NP", "NormalizedPower")
        np_str = f"NP: {round(float(np_val), 0)}W" if np_val is not None else ""

        # Decoupling & Efficiency
        pahr = _get_metric_val(totals, "Pa:Hr", "PaHr", "PacePulseDecoupling")
        pwhr = _get_metric_val(totals, "Pw:Hr", "PwHr", "PowerPulseDecoupling")
        ef = _get_metric_val(totals, "EF", "EfficiencyFactor")
        decoup_parts = []
        if pahr is not None:
            decoup_parts.append(f"Pa:Hr: {pahr}%")
        if pwhr is not None:
            decoup_parts.append(f"Pw:Hr: {pwhr}%")
        if ef is not None:
            decoup_parts.append(f"EF: {ef}")
        decoup_str = " | ".join(decoup_parts)

        # Elevation Gain & Loss
        el_gain = _get_metric_val(totals, "El. Gain", "ElevationGain", "TotalAscent")
        el_loss = _get_metric_val(totals, "El. Loss", "ElevationLoss", "TotalDescent")
        el_str = ""
        if el_gain is not None or el_loss is not None:
            g = f"+{el_gain}m" if el_gain is not None else ""
            l = f"-{el_loss}m" if el_loss is not None else ""
            el_str = f"Elevation: {' / '.join(filter(None, [g, l]))}"

        # Vertical Ascent Rate (VAM) & Average Grade
        vam_val = _get_metric_val(totals, "VAM", "AverageVam")
        vam_str = f"VAM: {int(round(float(vam_val)))}m/h" if (vam_val is not None and float(vam_val) > 0) else ""

        grade_val = _get_metric_val(totals, "Grade", "AverageGrade")
        grade_str = f"Grade: {round(float(grade_val), 1)}%" if (grade_val is not None and float(grade_val) != 0) else ""

        summary_parts = [p for p in [dist_str, dur_str, pace_str, tss_str, if_str, np_str, decoup_str, el_str, vam_str, grade_str] if p]
        if summary_parts:
            lines.append("Totals: " + " | ".join(summary_parts))

    if isinstance(channels, list) and channels:
        ch_items = []
        for ch in channels:
            if isinstance(ch, dict) and ch.get("identifier") in ALLOWED_DATA_CHANNELS:
                name = ch.get("name") or ch.get("identifier")
                unit = ch.get("unit", "")
                avg_val = ch.get("average")
                min_val = ch.get("min")
                max_val = ch.get("max")
                if avg_val is not None:
                    if name == "Power" and unit == "watts":
                        unit = "W"
                    elif name == "Cadence" and unit == "spm":
                        unit = "spm"
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

    if isinstance(laps, list) and laps:
        lines.append("Laps Breakdown:")
        for idx, lap in enumerate(laps, start=1):
            if not isinstance(lap, dict):
                continue
            l_num = lap.get("Name") or lap.get("lapNumber") or lap.get("lapIndex") or f"Lap {idx}"
            if not str(l_num).lower().startswith("lap"):
                l_num = f"Lap {l_num}"

            dur_s = lap.get("TotalTimerTime", lap.get("TotalMovingTime", lap.get("TotalElapsedTime", lap.get("duration_seconds", lap.get("duration", 0)))))
            dur_str = f"{round(dur_s / 60.0, 1)}m" if dur_s else ""

            # Lap Distance
            lap_dist = lap.get("TotalDistance", lap.get("distance_km", lap.get("Distance", lap.get("distance", 0))))
            dist_str = ""
            if lap_dist:
                try:
                    ld = float(lap_dist)
                    ld_km = ld / 1000.0 if ld > 50 else ld
                    dist_str = f"{round(ld_km, 2)}km"
                except (ValueError, TypeError):
                    dist_str = f"{lap_dist}km"

            avg_hr = lap.get("AverageHeartRate")
            max_hr = lap.get("MaximumHeartRate")
            hr_str = f"HR {avg_hr}/{max_hr}bpm" if (avg_hr and max_hr) else f"HR {avg_hr}bpm" if avg_hr else ""

            # Pace & Lap NGP comparison
            raw_pace = lap.get("AveragePace")
            lap_ngp = lap.get("NormalizedGradedPace")
            pace_str = ""
            if raw_pace is not None:
                p_str = _format_pace(raw_pace)
                if lap_ngp is not None and abs(float(raw_pace) - float(lap_ngp)) >= 3:
                    ngp_str = _format_pace(lap_ngp)
                    pace_str = f"Pace {p_str} (NGP {ngp_str})"
                else:
                    pace_str = f"Pace {p_str}"
            elif lap_ngp is not None:
                pace_str = f"NGP {_format_pace(lap_ngp)}"

            # Lap Elevation & Grade
            ascent = lap.get("TotalAscent")
            descent = lap.get("TotalDescent")
            lap_el_str = ""
            if (ascent is not None and ascent > 0) or (descent is not None and descent > 0):
                g_str = f"+{ascent}m" if ascent else "+0m"
                d_str = f"-{descent}m" if descent else "-0m"
                lap_el_str = f"Elev {g_str}/{d_str}"

            lap_grade = lap.get("AverageGrade")
            grade_str = f"Grade {lap_grade}%" if (lap_grade is not None and lap_grade != 0) else ""

            lap_vam = lap.get("AverageVam")
            lap_vam_str = f"VAM {int(round(float(lap_vam)))}m/h" if (lap_vam is not None and float(lap_vam) >= 50) else ""

            pwr = lap.get("AveragePower") or lap.get("NormalizedPower")
            pwr_str = f"Pwr {pwr}W" if pwr else ""

            cad = lap.get("AverageCadence")
            cad_str = f"Cad {cad}spm" if cad else ""

            decoup = lap.get("PacePulseDecoupling") or lap.get("PowerPulseDecoupling")
            decoup_str = f"Pa:Hr {decoup}%" if decoup is not None else ""

            # Running Dynamics (POD 2 / Stryd / Garmin RD)
            gct = lap.get("AverageStanceTime") or lap.get("AverageGroundContactTime") or lap.get("groundContactTime") or lap.get("ContactTime") or lap.get("gct")
            gct_str = f"GCT {round(gct, 1)}ms" if isinstance(gct, (int, float)) else f"GCT {gct}" if gct else ""

            bal = lap.get("AverageGroundContactTimeBalance") or lap.get("groundContactTimeBalance") or lap.get("gctBalance")
            bal_str = f"Bal {bal}" if bal else ""

            vert = lap.get("AverageVerticalOscillation") or lap.get("verticalOscillation") or lap.get("vertOsc")
            vert_str = ""
            if vert is not None:
                if isinstance(vert, (int, float)):
                    v_cm = vert / 10.0 if vert > 20 else vert
                    vert_str = f"Vert {round(v_cm, 1)}cm"
                else:
                    vert_str = f"Vert {vert}"

            stride = lap.get("AverageStepLength") or lap.get("AverageStrideLength") or lap.get("strideLength") or lap.get("stepLength")
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
