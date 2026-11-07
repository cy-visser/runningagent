from typing import Optional

from ....shared.athlete_settings import sport_family
from ....shared.units import fmt_clock, fmt_pace
from ....shared.workout_structure import (
    COOLDOWN_INTENSITY,
    PA_HR_SKIP_S,
    WARMUP_INTENSITY,
    Alignment,
    ExecutedStep,
    PlannedStep,
    align_laps,
    decoupling_label,
    flatten_structure,
    lap_km,
    lap_time,
    windowed_decoupling,
)

# Per-block decoupling is reported for work blocks at least this long.
MIN_BLOCK_S = 8 * 60


def _fmt_length(step: PlannedStep) -> str:
    if step.open_duration:
        return "open (lap button)"
    if step.length_m is not None:
        return f"{step.length_m / 1000:.2f} km" if step.length_m >= 1000 else f"{int(step.length_m)} m"
    if step.length_s is not None:
        return f"{int(step.length_s)}s" if step.length_s < 60 else fmt_clock(step.length_s)
    return "-"


def target_range(step: PlannedStep, metric: Optional[str], thr: dict) -> Optional[tuple[str, float, float]]:
    """(kind, low, high) in real units: kind 'pace' (s/km, low=fast), 'hr' (bpm) or 'power' (W)."""
    lo, hi = step.target_lo, step.target_hi
    if lo is None or hi is None:
        return None
    metric = metric or ""
    if metric == "percentOfThresholdPace" and thr.get("threshold_speed"):
        thr_pace = 1000.0 / thr["threshold_speed"]
        return ("pace", round(thr_pace / (hi / 100.0)), round(thr_pace / (lo / 100.0)))
    if metric == "percentOfThresholdHr" and thr.get("lthr"):
        return ("hr", round(thr["lthr"] * lo / 100.0), round(thr["lthr"] * hi / 100.0))
    if metric == "percentOfFtp" and thr.get("ftp"):
        return ("power", round(thr["ftp"] * lo / 100.0), round(thr["ftp"] * hi / 100.0))
    return None


def format_target(step: PlannedStep, metric: Optional[str], thr: dict) -> str:
    rng = target_range(step, metric, thr)
    if rng:
        kind, lo, hi = rng
        if kind == "pace":
            return f"{fmt_clock(lo)}–{fmt_pace(hi)}"
        return f"{int(lo)}–{int(hi)} {'bpm' if kind == 'hr' else 'W'}"
    if step.target_lo is None:
        return "no target"
    label = {"percentOfThresholdPace": "% thr pace", "percentOfThresholdHr": "% LTHR",
             "percentOfFtp": "% FTP"}.get(metric or "", f"% ({metric})")
    return f"{step.target_lo:g}–{step.target_hi:g}{label}"


def target_delta(ex: ExecutedStep, metric: Optional[str], thr: dict) -> Optional[tuple[float, str]]:
    """(signed distance to the nearest target edge, unit); 0 inside the range; None when unknown.

    Pace: negative = faster than the range. HR / power: negative = below the range.
    """
    rng = target_range(ex.step, metric, thr)
    if not rng:
        return None
    kind, lo, hi = rng
    actual, unit = {"pace": (ex.pace_s, "s/km"), "hr": (ex.hr_avg, "bpm")}.get(kind, (ex.power, "W"))
    if actual is None:
        return None
    if actual < lo:
        return actual - lo, unit
    if actual > hi:
        return actual - hi, unit
    return 0.0, unit


def format_target_delta(delta: Optional[tuple[float, str]]) -> str:
    """'0' inside the range, '-4 s/km' / '+6 bpm' / '-12 W' outside it, '' when unknown."""
    if delta is None:
        return ""
    value, unit = delta
    return "0" if round(value) == 0 else f"{round(value):+d} {unit}"


def _block_intensity(steps: list[ExecutedStep]) -> float:
    pairs = [((e.step.target_lo + e.step.target_hi) / 2, e.dur_s) for e in steps
             if e.step.target_lo is not None and e.step.target_hi is not None and e.dur_s > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else 0.0


def _step_label(step: PlannedStep) -> str:
    if step.block_reps > 1:
        return f"B{step.block} {step.name} {step.rep}/{step.block_reps}"
    return f"B{step.block} {step.name}"


def format_planned_structure(steps: list[PlannedStep], metric: Optional[str], thr: dict) -> str:
    """Plan-only view (laps could not be aligned)."""
    lines, seen = [], set()
    for s in steps:
        if (s.block, s.pos) in seen:
            continue
        seen.add((s.block, s.pos))
        reps = f"{s.block_reps}× " if s.block_reps > 1 else ""
        lines.append(f"- B{s.block}: {reps}{s.name} {_fmt_length(s)} @ {format_target(s, metric, thr)}")
    return "\n".join(lines)


def format_structured_execution(
    structured_workout: dict,
    laps: Optional[list[dict]],
    thr: dict,
    series: Optional[list[dict]],
    sport: Optional[str],
    alignment: Optional[Alignment] = None,
) -> str:
    """Planned-vs-executed section for a TP structured workout."""
    metric = structured_workout.get("primaryIntensityMetric")
    steps = flatten_structure(structured_workout)
    if not steps:
        return ""
    is_bike = sport_family(sport) == "bike"
    thr_bits = []
    if thr.get("threshold_speed") and not is_bike:
        thr_bits.append(f"threshold pace {fmt_pace(1000 / thr['threshold_speed'])}")
    if thr.get("lthr"):
        thr_bits.append(f"LTHR {int(thr['lthr'])} bpm")
    if thr.get("ftp") and is_bike:
        thr_bits.append(f"FTP {int(thr['ftp'])} W")
    header = "### Planned structure & execution" + (f" ({', '.join(thr_bits)})" if thr_bits else "")

    if alignment is None:
        alignment = align_laps(steps, laps or [])
    if alignment is None:
        return (f"{header}\nDevice laps do not line up with the planned steps; planned structure:\n"
                f"{format_planned_structure(steps, metric, thr)}")

    actual_col = "Power" if is_bike else "Pace"
    lines = [header, f"| Step | Planned | Target | {actual_col} | HR avg/max | Cad | Δ vs target |",
             "|---|---|---|---|---|---|---|"]
    for e in alignment.steps:
        actual = f"{round(e.power)} W" if is_bike and e.power else fmt_pace(e.pace_s)
        hr = f"{round(e.hr_avg)}/{round(e.hr_max)}" if e.hr_avg and e.hr_max else (f"{round(e.hr_avg)}" if e.hr_avg else "-")
        cad = f"{round(e.cadence)}" if e.cadence else "-"
        lines.append(f"| {_step_label(e.step)} | {_fmt_length(e.step)} | {format_target(e.step, metric, thr)} "
                     f"| {actual} | {hr} | {cad} | {format_target_delta(target_delta(e, metric, thr))} |")
    for lap in alignment.extra_laps:
        lines.append(f"Extra lap (not in plan): {lap.get('Name') or 'lap'} {fmt_clock(lap_time(lap))}, {lap_km(lap):.2f} km")

    # Repeated blocks: rep-to-rep consistency and HR drift.
    blocks: dict[int, list[ExecutedStep]] = {}
    for e in alignment.steps:
        blocks.setdefault(e.step.block, []).append(e)
    rep_lines = []
    for b, execs in blocks.items():
        if execs[0].step.block_reps < 2:
            continue
        positions: dict[int, list[ExecutedStep]] = {}
        for e in execs:
            positions.setdefault(e.step.pos, []).append(e)
        desc = " / ".join(
            f"{p[0].step.name} {_fmt_length(p[0].step)} @ {format_target(p[0].step, metric, thr)}" for p in positions.values()
        )
        rep_lines.append(f"- B{b} {execs[0].step.block_reps}× ({desc}):")
        for p in positions.values():
            parts = []
            if is_bike:
                vals = [e.power for e in p if e.power]
                if vals:
                    parts.append(f"power {', '.join(str(round(v)) for v in vals)} W (spread {round(max(vals) - min(vals))} W)")
            else:
                vals = [e.pace_s for e in p if e.pace_s]
                if vals:
                    parts.append(f"pace {', '.join(fmt_clock(v) for v in vals)} (spread {round(max(vals) - min(vals))}s)")
            hrs = [e.hr_avg for e in p if e.hr_avg]
            if len(hrs) >= 2:
                parts.append(f"HR {' → '.join(str(round(h)) for h in hrs)} ({round(hrs[-1] - hrs[0]):+d} bpm first→last)")
            deltas = [target_delta(e, metric, thr) for e in p]
            if any(d is not None for d in deltas):
                inside = sum(1 for d in deltas if d is not None and round(d[0]) == 0)
                parts.append(f"{inside}/{len(p)} within the target range")
            rep_lines.append(f"  - {p[0].step.name}: " + " | ".join(parts))
    if rep_lines:
        lines += ["", "**Repeated blocks:**", *rep_lines]

    # Per-block decoupling for work blocks >= MIN_BLOCK_S (the first minutes are always skipped).
    block_rows = []
    for b, execs in blocks.items():
        if all(e.step.intensity in (WARMUP_INTENSITY, COOLDOWN_INTENSITY) for e in execs):
            continue
        t0, t1 = max(execs[0].start, float(PA_HR_SKIP_S)), execs[-1].end
        if t1 - t0 < MIN_BLOCK_S:
            continue
        value, source = windowed_decoupling(series, [l for e in execs for l in e.laps], t0, t1, sport)
        if value is not None:
            block_rows.append((b, execs, t0, t1, value, source))
    if block_rows:
        key_block = max(block_rows, key=lambda r: _block_intensity(r[1]))[0] if len(block_rows) > 1 else None
        lines += ["", "**Decoupling per work block** (EF first vs second half):"]
        for b, execs, t0, t1, value, source in block_rows:
            reps = f"{execs[0].step.block_reps}× " if execs[0].step.block_reps > 1 else ""
            names = "/".join(dict.fromkeys(e.step.name for e in execs))
            key = " [highest target intensity]" if b == key_block else ""
            lines.append(f"- B{b} {reps}{names}: {decoupling_label(sport, t0, t1, source)}: {value}%{key}")
    return "\n".join(lines)
