from datetime import date
from typing import Any, Optional
from ..utils.date_helpers import parse_date
from .metrics import parse_mcp_response

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
    "GroundContactTime", "ContactTime", "GCT",
    "GroundContactTimeBalance", "GCTBalance", "ContactTimeBalance", "Balance",
    "VerticalOscillation", "VertOsc",
    "StrideLength", "StepLength",
    "VerticalRatio",
}

def format_workout_analysis(data: Optional[dict]) -> str:
    """Sanitizes and formats raw TrainingPeaks workout analysis directly into a token-efficient text summary."""
    if not data or not isinstance(data, dict):
        return "No analysis data returned."

    w_id = data.get("workoutId", "")
    totals = data.get("totals", {})
    channels = data.get("dataChannels", [])
    laps = data.get("lapData", [])

    lines = [f"### Workout Analysis [{w_id}]"]

    if totals:
        dur_s = totals.get("duration", 0)
        dur_str = f"{round(dur_s / 60.0, 1)}m" if dur_s else ""
        dist_m = totals.get("distance", 0)
        dist_str = f"{round(dist_m / 1000.0, 2)}km" if dist_m else ""
        tss = totals.get("tss", 0)
        intensity = totals.get("intensityFactor", 0)
        parts = [p for p in [dist_str, dur_str, f"TSS: {tss}" if tss else "", f"IF: {intensity}" if intensity else ""] if p]
        if parts:
            lines.append("Totals: " + " | ".join(parts))

    if isinstance(channels, list) and channels:
        ch_items = []
        for ch in channels:
            if isinstance(ch, dict) and ch.get("identifier") in ALLOWED_DATA_CHANNELS:
                name = ch.get("name") or ch.get("identifier")
                unit = ch.get("unit", "")
                avg_val = ch.get("average")
                max_val = ch.get("max")
                if avg_val is not None:
                    max_str = f" (Max {max_val}{unit})" if max_val is not None else ""
                    ch_items.append(f"{name}: Avg {avg_val}{unit}{max_str}")
        if ch_items:
            lines.append("Channels: " + " | ".join(ch_items))

    if isinstance(laps, list) and laps:
        lines.append("Laps Breakdown:")
        for idx, lap in enumerate(laps, start=1):
            if not isinstance(lap, dict):
                continue
            l_num = lap.get("lapNumber", lap.get("lapIndex", idx))
            dur_s = lap.get("duration_seconds", lap.get("TotalElapsedTime", lap.get("duration", 0)))
            dur_str = f"{round(dur_s / 60.0, 1)}m" if dur_s else ""
            dist_m = lap.get("distance", lap.get("Distance", 0))
            dist_str = f"{round(dist_m / 1000.0, 2)}km" if dist_m else ""
            avg_hr = lap.get("AverageHeartRate")
            max_hr = lap.get("MaximumHeartRate")
            hr_str = f"HR {avg_hr}/{max_hr}bpm" if avg_hr else ""
            pace_str = f"Pace {lap.get('AveragePace')}" if lap.get("AveragePace") else ""
            pwr_str = f"Pwr {lap.get('AveragePower')}W" if lap.get("AveragePower") else ""
            cad_str = f"Cad {lap.get('AverageCadence')}rpm" if lap.get("AverageCadence") else ""
            
            # Running Dynamics (POD 2 / Stryd / Garmin RD)
            gct = lap.get("AverageGroundContactTime") or lap.get("groundContactTime") or lap.get("ContactTime") or lap.get("gct")
            gct_str = f"GCT {round(gct, 1)}ms" if isinstance(gct, (int, float)) else f"GCT {gct}" if gct else ""
            
            bal = lap.get("AverageGroundContactTimeBalance") or lap.get("groundContactTimeBalance") or lap.get("gctBalance")
            bal_str = f"Bal {bal}" if bal else ""
            
            vert = lap.get("AverageVerticalOscillation") or lap.get("verticalOscillation") or lap.get("vertOsc")
            vert_str = f"Vert {round(vert, 1)}cm" if isinstance(vert, (int, float)) else f"Vert {vert}" if vert else ""
            
            stride = lap.get("AverageStrideLength") or lap.get("strideLength") or lap.get("stepLength")
            stride_str = f"Stride {round(stride, 2)}m" if isinstance(stride, (int, float)) else f"Stride {stride}" if stride else ""
            
            lap_parts = [p for p in [dur_str, dist_str, pace_str, hr_str, pwr_str, cad_str, gct_str, bal_str, vert_str, stride_str] if p]
            lines.append(f"- Lap {l_num}: " + " | ".join(lap_parts))

    return "\n".join(lines)
