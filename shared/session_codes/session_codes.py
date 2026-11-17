"""Session-code language shared by plan-builder and workout-creator: one compact code -> an exact TP session.

The coach plans in codes (`E 10`, `T 2x15' r2'`, `L 28 +8@M`, `B 4x8' @SS r4'`, `S 45' heavy-lower`, ...);
this module turns each code into the session the app writes: sport, title, coded description and, for
runs and rides, the coach-format structure fed through shared.workout_builder (exact native builder,
totals, summary) and shared.strides (strides after the warm-up of quality runs). Targets come from the
resolved zone table (pace_zones), never from the LLM.
"""

import re
from datetime import date
from typing import Any, Optional

from ..strides import ADDED, default_strides, ensure_strides
from ..workout_builder import NOMINAL_SPEED_MPS, builder_summary, builder_totals, parse_coach_structure
from .pace_zones import run_band
from .strength_templates import FOCI, focus_key, strength_session


class CodeError(ValueError):
    """A session code that cannot be built (the message says why, for the coach)."""


RUN_KINDS = ("E", "R", "L", "T", "I", "RP", "M", "P", "H")
RACE_KINDS = ("RACE", "EVENT")
# Quality runs: warm-up, strides, main set, cool-down.
QUALITY_KINDS = ("T", "I", "RP", "M", "P", "H")
STRIDE_KINDS = ("T", "I", "RP", "M", "P")
WARMUP_S, COOLDOWN_S, BIKE_WARMUP_S, BIKE_COOLDOWN_S = 900, 600, 900, 600
DEFAULT_RECOVERY = {"T": ("s", 120), "I": ("s", 120), "RP": ("m", 200), "M": ("s", 120), "P": ("s", 120),
                    "H": ("s", 90), "B": ("s", 240)}
DEFAULT_PACE = {"T": "T", "I": "I", "RP": "Rp", "M": "M", "H": "H"}
PACE_ALIASES = {"T": "T", "I": "I", "RP": "Rp", "H": "H", "E": "E", "L": "L", "R": "R",
                "5K": "5K", "10K": "10K", "HM": "HM", "M": "M", "MP": "M", "HMP": "HM"}
BIKE_INTENSITY = {"SS": "Sweet Spot", "T": "Threshold Ride", "VO2": "VO2 Ride", "Z3": "Tempo Ride"}
BIKE_STEADY = {"Z1": "Recovery Ride", "Z2": "Endurance Ride", "Z3": "Tempo Ride"}
CROSS_SPORTS = {"swim": "Swim", "walk": "Walk", "hike": "Walk", "crosstrain": "Crosstrain", "xt": "Crosstrain",
                "elliptical": "Crosstrain", "row": "Crosstrain", "yoga": "Crosstrain"}
CROSS_TSS_PER_MIN = {"Swim": 0.8, "Walk": 0.35, "Crosstrain": 0.6}
TIMES_OF_DAY = {"am": "07:00", "mid": "13:00", "pm": "18:00"}

SUMMARY_CHARS = 120

_TITLES = {"T": "Threshold", "I": "Intervals", "RP": "Speed Reps", "M": "Marathon Pace", "H": "Hill Reps"}
_STEP_NAMES = {"T": "Threshold", "I": "VO2max", "RP": "Speed", "M": "Marathon pace", "H": "Hill"}
_GOAL_TITLES = {"5K": "5K Pace", "10K": "10K Pace", "HM": "HM Pace", "M": "Marathon Pace"}
_CUES = {
    "E": "Conversational and relaxed (HR zone 1-2).",
    "R": "Very easy: short, light strides; recovery is the goal.",
    "L": "Start easy and stay relaxed; fuel every 30-45' on runs over 75'.",
    "T": "Comfortably hard and even; never race the reps.",
    "I": "Hard but even reps; jog the recoveries.",
    "RP": "Fast and relaxed with good form; full recovery between reps.",
    "M": "Lock into goal pace; practise race fuelling.",
    "P": "Lock into goal pace; even splits.",
    "H": "Strong uphill effort, jog back down; effort leads, the pace is a guide.",
    "RACE": "Race day: 10-15' easy with strides before the start.",
    "EVENT": "Controlled event effort: lock into target pace and resist racing the crowd.",
}

_H_RE = re.compile(r"^(\d+)h(?:(\d{1,2})'?)?$")
_MIN_RE = re.compile(r"^(\d+)(?:'|min)(?:(\d{1,2})\")?$")
_SEC_RE = re.compile(r"^(\d+)(?:\"|s|sec)$")
_KM_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:k|km)$")
_MI_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:mi|miles?)$")
_M_RE = re.compile(r"^(\d+(?:\.\d+)?)m$")
_BARE_RE = re.compile(r"^(\d+(?:\.\d+)?)$")
_REPS_RE = re.compile(r"^(\d+)x(.+)$")
# A bare number below this is km ('E 10'), otherwise metres ('Rp 10x200').
BARE_KM_BELOW = 50


def normalize(code: Any) -> str:
    text = str(code or "")
    for src, dst in (("’", "'"), ("‘", "'"), ("′", "'"), ("″", '"'), ("“", '"'), ("”", '"'), ("×", "x")):
        text = text.replace(src, dst)
    text = re.sub(r"\+\s+", "+", text)
    text = re.sub(r"\s+@", " @", text)
    return " ".join(text.split())


def code_sport(code: Any) -> Optional[str]:
    """Inferred TrainingPeaks sport for a session code ('Run', 'Bike', 'Strength', 'Swim', 'Walk',
    'Crosstrain'), or None for empty / REST / unknown codes."""
    tokens = normalize(code).split()
    if not tokens:
        return None
    head = tokens[0].upper()
    if head in RUN_KINDS or head in RACE_KINDS:
        return "Run"
    if head == "B":
        return "Bike"
    if head == "S":
        return "Strength"
    if head == "X":
        words = [t.lower() for t in tokens[1:] if not re.match(r"^\d", t) and t.lower() not in TIMES_OF_DAY]
        return CROSS_SPORTS.get(" ".join(words)) or "Crosstrain"
    return None


def parse_length(token: str) -> tuple[str, float]:
    """('s', seconds) or ('m', metres) of a length token: 50', 1h30, 90", 2'30", 10, 1k, 10mi, 400m, 200."""
    t = token.lower()
    if m := _H_RE.match(t):
        return "s", int(m[1]) * 3600 + int(m[2] or 0) * 60
    if m := _MIN_RE.match(t):
        return "s", int(m[1]) * 60 + int(m[2] or 0)
    if m := _SEC_RE.match(t):
        return "s", int(m[1])
    if m := _KM_RE.match(t):
        return "m", float(m[1]) * 1000
    if m := _MI_RE.match(t):
        return "m", round(float(m[1]) * 1609.344, 1)
    if m := _M_RE.match(t):
        return "m", float(m[1])
    if m := _BARE_RE.match(t):
        value = float(m[1])
        return "m", value * 1000 if value < BARE_KM_BELOW else value
    raise CodeError(f"unreadable length '{token}' (use km like 10 / 1k / 10mi / 400m, or time like 50' / 90\" / 1h30)")


def length_text(length: tuple[str, float]) -> str:
    unit, value = length
    if unit == "m":
        if value >= 1000:
            km = round(value / 1000, 1) if value % 10 else value / 1000
            return f"{km:g} km"
        return f"{value:g} m"
    if value < 60:
        return f'{value:g}"'
    minutes, seconds = divmod(int(value), 60)
    if seconds:
        return f"{minutes}'{seconds:02d}\""
    if minutes < 90:
        return f"{minutes}'"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h{rest:02d}'" if rest else f"{hours}h"


def _step(name: str, cls: str, length: tuple[str, float], band: list[int]) -> dict:
    step: dict[str, Any] = {"name": name, "intensityClass": cls, "intensity_min": band[0], "intensity_max": band[1]}
    step["distance_m" if length[0] == "m" else "duration_seconds"] = round(length[1], 1)
    return step


def _positive(length: tuple[str, float], what: str) -> tuple[str, float]:
    if length[1] <= 0:
        raise CodeError(f"{what} must be > 0")
    return length


def _length_in_unit(length: tuple[str, float], band: list[int], unit: str, thr: dict) -> float:
    if length[0] == unit:
        return length[1]
    speed = (
        thr["threshold_speed"] * band[0] / 100.0
        if thr.get("threshold_speed") and band[0]
        else NOMINAL_SPEED_MPS
    )
    return float(round(length[1] * speed)) if unit == "m" else round(length[1] / speed, 1)


def _split_tokens(code: str) -> list[str]:
    out = []
    for token in code.split()[1:]:
        if "@" in token and not token.startswith(("@", "+")):
            head, tail = token.split("@", 1)
            out += [head, "@" + tail]
        else:
            out.append(token)
    return out


def _parse(code: str) -> dict:
    """Kind and its parts: main, reps, pace, recovery, zone, segments, words, raw_words, strides, time."""
    tokens = code.split()
    if not tokens:
        raise CodeError("empty session code")
    parsed: dict[str, Any] = {"kind": tokens[0].upper(), "words": [], "raw_words": [], "strides": False,
                              "time": None, "pace": None, "recovery": None, "segments": [], "main": None, "reps": 1}
    for token in _split_tokens(code):
        low = token.lower()
        if low in ("+strides", "+st"):
            parsed["strides"] = True
        elif low in TIMES_OF_DAY:
            parsed["time"] = TIMES_OF_DAY[low]
        elif token.startswith("@"):
            parsed["pace"] = token[1:].upper()
        elif token.startswith("+"):
            if "@" not in token:
                raise CodeError(f"'{token}': a segment needs a pace, e.g. +8@M or +4x4k@HM")
            seg, pace = token[1:].split("@", 1)
            if m := _REPS_RE.match(seg.lower()):
                seg_reps, seg_len = int(m[1]), parse_length(m[2])
            else:
                seg_reps, seg_len = 1, parse_length(seg)
            if seg_reps < 1:
                raise CodeError("reps must be at least 1")
            parsed["segments"].append({"reps": seg_reps, "length": seg_len, "pace": pace.upper(), "recovery": None})
        elif re.match(r"^r\d", low):
            rec = parse_length(token[1:])
            if parsed["segments"]:
                parsed["segments"][-1]["recovery"] = rec
            else:
                parsed["recovery"] = rec
        elif re.match(r"^z[1-3]$", low) and parsed["kind"] not in RACE_KINDS:
            parsed["zone"] = low.upper()
        elif parsed["main"] is None and (m := _REPS_RE.match(low)):
            reps = int(m[1])
            if reps < 1:
                raise CodeError("reps must be at least 1")
            parsed["reps"], parsed["main"] = reps, parse_length(m[2])
        elif parsed["main"] is None and re.match(r"^\d", token):
            parsed["main"] = parse_length(token)
        else:
            parsed["words"].append(low)
            parsed["raw_words"].append(token)
    return parsed


def _pace_key(parsed: dict, kind: str) -> str:
    raw = parsed["pace"] or DEFAULT_PACE.get(kind)
    if raw is None:
        raise CodeError("a race-pace session needs its pace: @5K, @10K, @HM or @M")
    key = PACE_ALIASES.get(raw.upper())
    if key is None:
        raise CodeError(f"unknown pace '@{raw}' (use @T, @I, @Rp, @H, @E, @5K, @10K, @HM or @M)")
    return key


def _need_main(parsed: dict, what: str) -> tuple[str, float]:
    if parsed["main"] is None:
        raise CodeError(f"{what} needs a length")
    return _positive(parsed["main"], what)


# ------------------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------------------

def _steady_run(parsed: dict, kind: str, zones: dict, allow_strides: bool = True) -> tuple[dict, str, Optional[str]]:
    main = _need_main(parsed, "the run")
    if parsed["pace"]:
        raise CodeError("easy, recovery and long runs take no @pace (a long-run segment is +8@M or +4x4k@HM)")
    zone = {"E": "E", "R": "R", "L": "L"}[kind]
    name = {"E": "Easy", "R": "Recovery", "L": "Long run"}[kind]
    title = {"E": "Easy Run", "R": "Recovery Run", "L": "Long Run"}[kind] + f" {length_text(main)}"
    steps: list[dict] = [_step(name, "active", main, run_band(zones, zone))]
    extra_cue = None
    segments = parsed["segments"]
    if segments:
        if kind != "L":
            raise CodeError("fast-finish or block segments (+8@M, +4x4k@HM) are only for long runs")
        thr = zones["thr"]["run"]
        seg_blocks: list[dict] = []
        seg_labels: list[str] = []
        used = 0.0
        single_finish = len(segments) == 1 and segments[0]["reps"] == 1
        for seg in segments:
            pace = PACE_ALIASES.get(seg["pace"])
            if pace is None or (single_finish and pace in ("E", "L", "R")):
                raise CodeError(f"unknown long-run segment pace '@{seg['pace']}' (use @M, @HM, @10K or @T)")
            reps, seg_len = seg["reps"], _positive(seg["length"], "segment length")
            band = run_band(zones, pace)
            work = _step(f"@{pace}", "active", seg_len, band)
            if reps > 1:
                rec = _positive(seg["recovery"] or parsed["recovery"] or DEFAULT_RECOVERY["P"], "recovery")
                jog_band = run_band(zones, "JOG")
                seg_blocks.append({"type": "repetition", "reps": reps,
                                   "steps": [work, _step("Jog", "rest", rec, jog_band)]})
                used += reps * (
                    _length_in_unit(seg_len, band, main[0], thr)
                    + _length_in_unit(rec, jog_band, main[0], thr)
                )
                seg_labels.append(f"{reps}x{length_text(seg_len).replace(' ', '')} @{pace}")
            else:
                seg_blocks.append(work)
                used += _length_in_unit(seg_len, band, main[0], thr)
                seg_labels.append(f"{length_text(seg_len).replace(' ', '')} @{pace}")
        if used >= main[1]:
            raise CodeError("long-run segments must be shorter than the total run")
        steps = [_step(name, "active", (main[0], main[1] - used), run_band(zones, "L")), *seg_blocks]
        if single_finish:
            seg_len = segments[0]["length"]
            pace = PACE_ALIASES[segments[0]["pace"]]
            title += f" (last {length_text(seg_len)} @{pace})"
            extra_cue = f"Finish the last {length_text(seg_len)} at @{pace}."
        else:
            title += f" ({' + '.join(seg_labels)})"
            extra_cue = f"Build into {' then '.join(seg_labels)}."
    if parsed["strides"] and allow_strides:
        steps.append(default_strides())
        title += " + strides"
    return {"steps": steps}, title, extra_cue


def _quality_run(parsed: dict, kind: str, zones: dict) -> tuple[dict, str]:
    pace = _pace_key(parsed, kind)
    reps = parsed["reps"]
    main = _need_main(parsed, "the main set")
    name = _STEP_NAMES.get(kind) or f"@{pace}"
    work = _step(name, "active", main, run_band(zones, pace))
    if reps > 1:
        rec = _positive(parsed["recovery"] or DEFAULT_RECOVERY[kind], "recovery")
        block = {"type": "repetition", "reps": reps, "steps": [work, _step("Jog", "rest", rec, run_band(zones, "JOG"))]}
    else:
        block = work
    steps = [_step("Warm up", "warmUp", ("s", WARMUP_S), run_band(zones, "WU")), block,
             _step("Cool down", "coolDown", ("s", COOLDOWN_S), run_band(zones, "WU"))]
    base = _GOAL_TITLES[pace] if kind == "P" else ("Tempo" if kind == "T" and reps == 1 else _TITLES[kind])
    title = f"{base} {f'{reps}x' if reps > 1 else ''}{length_text(main).replace(' ', '')}"
    if parsed["pace"] and kind != "P" and pace != DEFAULT_PACE.get(kind):
        title += f" @{pace}"
    return {"steps": steps}, title


def _default_race_pace(km: float) -> str:
    if km <= 7.5:
        return "5K"
    if km <= 14.0:
        return "10K"
    if km <= 30.0:
        return "HM"
    return "M"


def _race(parsed: dict, zones: dict, day: Optional[date]) -> tuple[dict, str, str]:
    if parsed["reps"] > 1 or parsed["segments"] or parsed["strides"] or parsed["recovery"]:
        raise CodeError("RACE/EVENT is a single effort without reps, recovery, +segments, or +strides")
    kind = parsed["kind"]
    races = zones.get("races") or []
    exact_goal = next((r for r in races if day and r["date"] == day.isoformat()), None)
    label = " ".join(w.strip("\"'") for w in parsed["raw_words"] if w.strip("\"'")).strip()

    if parsed["main"] is not None:
        main = _positive(parsed["main"], "event distance")
        if main[0] != "m":
            raise CodeError("RACE/EVENT needs a distance (e.g. RACE 16k @HM or EVENT 10mi @M)")
        km = main[1] / 1000.0
        if parsed["pace"]:
            pace = PACE_ALIASES.get(parsed["pace"].upper())
            if pace is None:
                raise CodeError(f"unknown pace '@{parsed['pace']}' (use @5K, @10K, @HM, @M, @T, or @E)")
        elif kind == "EVENT":
            raise CodeError("EVENT needs a target pace (e.g. EVENT 16k @M or EVENT 10k @E)")
        elif exact_goal:
            pace = exact_goal["pace"]
        else:
            pace = _default_race_pace(km)

        controlled = kind == "EVENT" or pace in ("E", "L", "R") or (pace == "M" and km < 38.0)
        step = _step("Event" if controlled else "Race", "active", main, run_band(zones, pace))
        if controlled:
            title = f"Event: {label} (@{pace})" if label else f"Event {length_text(main)} (@{pace})"
            return {"steps": [step]}, title, _CUES["EVENT"]
        title = f"Race: {label}" if label else f"Race {length_text(main)}"
        return {"steps": [step]}, title, _CUES["RACE"]

    if kind == "EVENT":
        raise CodeError("EVENT needs a distance and @pace (e.g. EVENT 16k @M Tilburg 10mi)")
    race = exact_goal or (races[-1] if races else None)
    km = (race or {}).get("km")
    if not race or not km:
        raise CodeError("RACE needs a goal race with a distance in the runner's profile, or an explicit distance (e.g. RACE 16k @HM)")
    pace = PACE_ALIASES.get(parsed["pace"].upper()) if parsed["pace"] else race["pace"]
    if pace is None:
        raise CodeError(f"unknown pace '@{parsed['pace']}' (use @5K, @10K, @HM, @M, @T, or @E)")
    step = _step("Race", "active", ("m", km * 1000), run_band(zones, pace))
    return {"steps": [step]}, f"Race: {label or race['title']}", _CUES["RACE"]


def _run_session(
    parsed: dict,
    code: str,
    zones: dict,
    day: Optional[date],
    *,
    current_builder: Optional[dict] = None,
    allow_strides: bool = True,
    include_code_footer: bool = True,
) -> dict:
    kind = parsed["kind"]
    extra_cue = None
    strides_status = None
    race_cue: Optional[str] = None
    if kind in RACE_KINDS:
        structure, title, race_cue = _race(parsed, zones, day)
    elif kind in QUALITY_KINDS:
        structure, title = _quality_run(parsed, kind, zones)
    else:
        structure, title, extra_cue = _steady_run(parsed, kind, zones, allow_strides=allow_strides)
        if parsed["strides"] and allow_strides:
            strides_status = ADDED
    thr = zones["thr"]["run"]
    native, error = parse_coach_structure(structure, "Run", thr)
    if error:
        raise CodeError(error)
    if allow_strides and kind in QUALITY_KINDS:
        native, status = ensure_strides({"sport": "Run", "title": title}, native, current_builder, thr)
        strides_status = status
        if status is None and kind in STRIDE_KINDS:
            # Short reps (e.g. 10x200) are not a "quality run" for ensure_strides; plans still open them with strides.
            structure["steps"].insert(1, default_strides())
            native, error = parse_coach_structure(structure, "Run", thr)
            if error:
                raise CodeError(error)
            strides_status = ADDED
    cue = race_cue or " ".join(c for c in (_CUES[kind], extra_cue) if c)
    out = _with_totals({"sport": "Run", "kind": kind, "title": title}, native, thr, cue, code, include_code_footer)
    if strides_status:
        out["strides_added"] = strides_status
    return out


# ------------------------------------------------------------------------------
# Bike, strength, cross-training
# ------------------------------------------------------------------------------

def _bike_session(parsed: dict, code: str, zones: dict, *, include_code_footer: bool = True) -> dict:
    main = _need_main(parsed, "the ride")
    if main[0] != "s":
        raise CodeError("rides are planned in time (e.g. B 60' Z2)")
    reps = parsed["reps"]
    intensity = parsed["pace"] or (None if reps == 1 else parsed.get("zone") or "SS")
    if intensity and intensity not in BIKE_INTENSITY and intensity not in ("Z1", "Z2"):
        raise CodeError(f"unknown ride intensity '@{intensity}' (use Z1, Z2, Z3, @SS, @T or @VO2)")
    if reps > 1 and intensity not in BIKE_INTENSITY:
        raise CodeError("ride reps need an intensity: @SS, @T, @VO2 or @Z3 (a steady ride is one block, e.g. B 60' Z2)")
    bike = zones["bike"]
    if intensity in BIKE_INTENSITY and (reps > 1 or intensity != "Z3"):
        work = _step(BIKE_INTENSITY[intensity], "active", main, bike[intensity])
        if reps > 1:
            rec = _positive(parsed["recovery"] or DEFAULT_RECOVERY["B"], "recovery")
            if rec[0] != "s":
                raise CodeError("ride recoveries are in time (e.g. r4')")
            work = {"type": "repetition", "reps": reps, "steps": [work, _step("Easy", "rest", rec, bike["REC"])]}
        steps = [_step("Warm up", "warmUp", ("s", BIKE_WARMUP_S), bike["WU"]), work,
                 _step("Cool down", "coolDown", ("s", BIKE_COOLDOWN_S), bike["WU"])]
        title = f"{BIKE_INTENSITY[intensity]} {f'{reps}x' if reps > 1 else ''}{length_text(main)}"
    else:
        zone = parsed.get("zone") or intensity or "Z2"
        steps = [_step(BIKE_STEADY[zone], "active", main, bike[zone])]
        title = f"{BIKE_STEADY[zone]} {length_text(main)}"
    thr = zones["thr"]["bike"]
    native, error = parse_coach_structure({"steps": steps}, "Bike", thr)
    if error:
        raise CodeError(error)
    return _with_totals({"sport": "Bike", "kind": "B", "title": title}, native, thr,
                        "Smooth, steady cadence; this is low-impact aerobic load.", code, include_code_footer)


def _minutes(parsed: dict, what: str) -> int:
    main = _need_main(parsed, what)
    if main[0] != "s":
        raise CodeError(f"{what} is planned in time (e.g. 40')")
    minutes = round(main[1] / 60)
    if minutes < 1:
        raise CodeError(f"{what} must be at least 1 minute")
    return minutes


def _strength(parsed: dict, code: str, phase: Optional[str], *, include_code_footer: bool = True) -> dict:
    minutes = _minutes(parsed, "a strength session")
    focus = focus_key(" ".join(parsed["words"])) if parsed["words"] else None
    if not focus:
        raise CodeError(f"strength needs a focus: {', '.join(FOCI)}")
    s = strength_session(focus, minutes, phase)
    desc = f"{s['description']}\nPlan code: {code}" if include_code_footer else s["description"]
    return {"sport": "Strength", "kind": "S", "title": s["title"], "description": desc,
            "summary": s["summary"][:SUMMARY_CHARS], "exercises": s["exercises"], "load": s["load"],
            "structured_workout": None, "distance_km": None, "duration_minutes": minutes,
            "tss_planned": s["tss_planned"]}


def _cross(parsed: dict, code: str, *, include_code_footer: bool = True) -> dict:
    minutes = _minutes(parsed, "cross-training")
    sport = CROSS_SPORTS.get(" ".join(parsed["words"]))
    if not sport:
        raise CodeError("cross-training needs a sport: swim, walk or crosstrain")
    desc = f"Easy {sport.lower()}.\nPlan code: {code}" if include_code_footer else f"Easy {sport.lower()}."
    return {"sport": sport, "kind": "X", "title": f"{sport} {minutes}'", "description": desc,
            "summary": f"{minutes}' easy", "structured_workout": None, "distance_km": None,
            "duration_minutes": minutes, "tss_planned": round(minutes * CROSS_TSS_PER_MIN[sport])}


def _with_totals(
    base: dict, native: dict, thr: dict, cue: str, code: str, include_code_footer: bool = True
) -> dict:
    summary = builder_summary(native, thr)
    desc = f"{summary}\n{cue}\nPlan code: {code}" if include_code_footer else f"{summary}\n{cue}"
    return {**base, "description": desc, "summary": summary[:SUMMARY_CHARS],
            "structured_workout": native, **builder_totals(native, thr)}


def build_session(
    code: Any,
    zones: dict,
    phase: Optional[str] = None,
    day: Optional[date] = None,
    *,
    current_builder: Optional[dict] = None,
    allow_strides: bool = True,
    include_code_footer: bool = True,
) -> dict:
    """The session of one code: sport, kind, code, title, description, summary, structured_workout (runs and
    rides), distance_km / duration_minutes / tss_planned and time (from 'am' / 'mid' / 'pm', else None).

    Raises CodeError (why the code cannot be built). REST is not a session (plan_expand handles it).
    """
    text = normalize(code)
    parsed = _parse(text)
    kind = parsed["kind"]
    if kind in RUN_KINDS or kind in RACE_KINDS:
        session = _run_session(
            parsed,
            text,
            zones,
            day,
            current_builder=current_builder,
            allow_strides=allow_strides,
            include_code_footer=include_code_footer,
        )
    elif kind == "B":
        session = _bike_session(parsed, text, zones, include_code_footer=include_code_footer)
    elif kind == "S":
        session = _strength(parsed, text, phase, include_code_footer=include_code_footer)
    elif kind == "X":
        session = _cross(parsed, text, include_code_footer=include_code_footer)
    else:
        raise CodeError(f"unknown session type '{text.split()[0]}' (E R L T I Rp M P H RACE EVENT B S X or REST)")
    return {**session, "code": text, "time": parsed["time"]}
