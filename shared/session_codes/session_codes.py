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
from ..workout_builder import builder_summary, builder_totals, parse_coach_structure
from .pace_zones import run_band
from .strength_templates import FOCI, focus_key, strength_session


class CodeError(ValueError):
    """A session code that cannot be built (the message says why, for the coach)."""


RUN_KINDS = ("E", "R", "L", "T", "I", "RP", "M", "P", "H")
# Quality runs: warm-up, strides, main set, cool-down.
QUALITY_KINDS = ("T", "I", "RP", "M", "P", "H")
STRIDE_KINDS = ("T", "I", "RP", "M", "P")
WARMUP_S, COOLDOWN_S, BIKE_WARMUP_S, BIKE_COOLDOWN_S = 900, 600, 900, 600
DEFAULT_RECOVERY = {"T": ("s", 120), "I": ("s", 120), "RP": ("m", 200), "M": ("s", 120), "P": ("s", 120),
                    "H": ("s", 90), "B": ("s", 240)}
DEFAULT_PACE = {"T": "T", "I": "I", "RP": "Rp", "M": "M", "H": "H"}
PACE_ALIASES = {"T": "T", "I": "I", "RP": "Rp", "H": "H", "E": "E", "5K": "5K", "10K": "10K", "HM": "HM", "M": "M",
                "MP": "M", "HMP": "HM"}
BIKE_INTENSITY = {"SS": "Sweet Spot", "T": "Threshold Ride", "VO2": "VO2 Ride", "Z3": "Tempo Ride"}
BIKE_STEADY = {"Z1": "Recovery Ride", "Z2": "Endurance Ride", "Z3": "Tempo Ride"}
CROSS_SPORTS = {"swim": "Swim", "walk": "Walk", "hike": "Walk", "crosstrain": "Crosstrain", "xt": "Crosstrain",
                "elliptical": "Crosstrain", "row": "Crosstrain", "yoga": "Crosstrain"}
CROSS_TSS_PER_MIN = {"Swim": 0.8, "Walk": 0.35, "Crosstrain": 0.6}
TIMES_OF_DAY = {"am": "07:00", "mid": "13:00", "pm": "18:00"}

MAX_RUN_M, MAX_S = 60_000, 6 * 3600
MAX_REPS, MAX_REP_M, MAX_REP_S = 40, 10_000, 3600
STRENGTH_MINUTES, CROSS_MINUTES = (10, 120), (10, 300)
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
}

_H_RE = re.compile(r"^(\d+)h(?:(\d{1,2})'?)?$")
_MIN_RE = re.compile(r"^(\d+)(?:'|min)(?:(\d{1,2})\")?$")
_SEC_RE = re.compile(r"^(\d+)(?:\"|s|sec)$")
_KM_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:k|km)$")
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
    if head in RUN_KINDS or head == "RACE":
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
    """('s', seconds) or ('m', metres) of a length token: 50', 1h30, 90", 2'30", 10, 1k, 400m, 200."""
    t = token.lower()
    if m := _H_RE.match(t):
        return "s", int(m[1]) * 3600 + int(m[2] or 0) * 60
    if m := _MIN_RE.match(t):
        return "s", int(m[1]) * 60 + int(m[2] or 0)
    if m := _SEC_RE.match(t):
        return "s", int(m[1])
    if m := _KM_RE.match(t):
        return "m", float(m[1]) * 1000
    if m := _M_RE.match(t):
        return "m", float(m[1])
    if m := _BARE_RE.match(t):
        value = float(m[1])
        return "m", value * 1000 if value < BARE_KM_BELOW else value
    raise CodeError(f"unreadable length '{token}' (use km like 10 / 1k / 400m, or time like 50' / 90\" / 1h30)")


def length_text(length: tuple[str, float]) -> str:
    unit, value = length
    if unit == "m":
        return f"{value / 1000:g} km" if value >= 1000 else f"{value:g} m"
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


def _check(length: tuple[str, float], max_m: float, max_s: float, what: str) -> tuple[str, float]:
    limit = max_m if length[0] == "m" else max_s
    if not 0 < length[1] <= limit:
        raise CodeError(f"{what} {length_text(length)} is out of range")
    return length


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
    """Kind and its parts: main, reps, pace, recovery, zone, segment, words, strides, time."""
    tokens = code.split()
    if not tokens:
        raise CodeError("empty session code")
    parsed: dict[str, Any] = {"kind": tokens[0].upper(), "words": [], "strides": False, "time": None,
                              "pace": None, "recovery": None, "segment": None, "main": None, "reps": 1}
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
                raise CodeError(f"'{token}': a fast finish needs a pace, e.g. +8@M")
            seg, pace = token[1:].split("@", 1)
            parsed["segment"] = (parse_length(seg), pace.upper())
        elif re.match(r"^r\d", low):
            parsed["recovery"] = parse_length(token[1:])
        elif re.match(r"^z[1-3]$", low):
            parsed["zone"] = low.upper()
        elif parsed["main"] is None and (m := _REPS_RE.match(low)):
            parsed["reps"], parsed["main"] = int(m[1]), parse_length(m[2])
        elif parsed["main"] is None and re.match(r"^\d", token):
            parsed["main"] = parse_length(token)
        else:
            parsed["words"].append(low)
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
    return parsed["main"]


# ------------------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------------------

def _steady_run(parsed: dict, kind: str, zones: dict, allow_strides: bool = True) -> tuple[dict, str, Optional[str]]:
    main = _check(_need_main(parsed, "the run"), MAX_RUN_M, MAX_S, "run length")
    if parsed["pace"]:
        raise CodeError("easy, recovery and long runs take no @pace (a long-run fast finish is +8@M)")
    zone = {"E": "E", "R": "R", "L": "L"}[kind]
    name = {"E": "Easy", "R": "Recovery", "L": "Long run"}[kind]
    title = {"E": "Easy Run", "R": "Recovery Run", "L": "Long Run"}[kind] + f" {length_text(main)}"
    steps = [_step(name, "active", main, run_band(zones, zone))]
    extra_cue = None
    if parsed["segment"]:
        if kind != "L":
            raise CodeError("a fast finish (+8@M) is only for long runs")
        seg, raw_pace = parsed["segment"]
        pace = PACE_ALIASES.get(raw_pace)
        if pace is None or pace == "E":
            raise CodeError(f"unknown fast-finish pace '@{raw_pace}' (use @M, @HM, @10K or @T)")
        if seg[0] != main[0] or seg[1] >= main[1]:
            raise CodeError("the fast finish must be shorter than the run and in the same unit (km or time)")
        steps = [_step(name, "active", (main[0], main[1] - seg[1]), run_band(zones, "L")),
                 _step(f"@{pace}", "active", seg, run_band(zones, pace))]
        title += f" (last {length_text(seg)} @{pace})"
        extra_cue = f"Finish the last {length_text(seg)} at @{pace}."
    if parsed["strides"] and allow_strides:
        steps.append(default_strides())
        title += " + strides"
    return {"steps": steps}, title, extra_cue


def _quality_run(parsed: dict, kind: str, zones: dict) -> tuple[dict, str]:
    pace = _pace_key(parsed, kind)
    reps = parsed["reps"]
    if not 1 <= reps <= MAX_REPS:
        raise CodeError(f"reps must be 1 to {MAX_REPS}")
    main = _need_main(parsed, "the main set")
    main = _check(main, MAX_REP_M if reps > 1 else MAX_RUN_M, MAX_REP_S if reps > 1 else MAX_S, "rep length")
    name = _STEP_NAMES.get(kind) or f"@{pace}"
    work = _step(name, "active", main, run_band(zones, pace))
    if reps > 1:
        rec = _check(parsed["recovery"] or DEFAULT_RECOVERY[kind], MAX_REP_M, MAX_REP_S, "recovery")
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


def _race(parsed: dict, zones: dict, day: Optional[date]) -> tuple[dict, str]:
    races = zones.get("races") or []
    race = next((r for r in races if day and r["date"] == day.isoformat()), None) or (races[-1] if races else None)
    km = parsed["main"][1] / 1000 if parsed["main"] and parsed["main"][0] == "m" else (race or {}).get("km")
    if not race or not km:
        raise CodeError("RACE needs a goal race with a distance in the runner's profile")
    step = _step("Race", "active", ("m", km * 1000), run_band(zones, race["pace"]))
    return {"steps": [step]}, f"Race: {race['title']}"


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
    if kind == "RACE":
        structure, title = _race(parsed, zones, day)
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
    cue = " ".join(c for c in (_CUES[kind], extra_cue) if c)
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
        if not 1 <= reps <= MAX_REPS:
            raise CodeError(f"reps must be 1 to {MAX_REPS}")
        _check(main, 0, MAX_REP_S if reps > 1 else MAX_S, "rep length")
        work = _step(BIKE_INTENSITY[intensity], "active", main, bike[intensity])
        if reps > 1:
            rec = _check(parsed["recovery"] or DEFAULT_RECOVERY["B"], 0, MAX_REP_S, "recovery")
            if rec[0] != "s":
                raise CodeError("ride recoveries are in time (e.g. r4')")
            work = {"type": "repetition", "reps": reps, "steps": [work, _step("Easy", "rest", rec, bike["REC"])]}
        steps = [_step("Warm up", "warmUp", ("s", BIKE_WARMUP_S), bike["WU"]), work,
                 _step("Cool down", "coolDown", ("s", BIKE_COOLDOWN_S), bike["WU"])]
        title = f"{BIKE_INTENSITY[intensity]} {f'{reps}x' if reps > 1 else ''}{length_text(main)}"
    else:
        zone = parsed.get("zone") or intensity or "Z2"
        _check(main, 0, MAX_S, "ride length")
        steps = [_step(BIKE_STEADY[zone], "active", main, bike[zone])]
        title = f"{BIKE_STEADY[zone]} {length_text(main)}"
    thr = zones["thr"]["bike"]
    native, error = parse_coach_structure({"steps": steps}, "Bike", thr)
    if error:
        raise CodeError(error)
    return _with_totals({"sport": "Bike", "kind": "B", "title": title}, native, thr,
                        "Smooth, steady cadence; this is low-impact aerobic load.", code, include_code_footer)


def _minutes(parsed: dict, bounds: tuple[int, int], what: str) -> int:
    main = _need_main(parsed, what)
    if main[0] != "s":
        raise CodeError(f"{what} is planned in time (e.g. 40')")
    minutes = round(main[1] / 60)
    if not bounds[0] <= minutes <= bounds[1]:
        raise CodeError(f"{what} must be {bounds[0]}-{bounds[1]} minutes")
    return minutes


def _strength(parsed: dict, code: str, phase: Optional[str], *, include_code_footer: bool = True) -> dict:
    minutes = _minutes(parsed, STRENGTH_MINUTES, "a strength session")
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
    minutes = _minutes(parsed, CROSS_MINUTES, "cross-training")
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
    if kind in RUN_KINDS or kind == "RACE":
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
        raise CodeError(f"unknown session type '{text.split()[0]}' (E R L T I Rp M P H RACE B S X or REST)")
    return {**session, "code": text, "time": parsed["time"]}
