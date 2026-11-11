"""Strength session templates per focus, adjusted by training phase (coded descriptions, no LLM).

Phases: base = higher reps / general strength, build = heavy + reactive, peak = maintenance (lower
volume, same intensity), recovery = a lighter week, taper = activation only. TSS is estimated per minute
by focus so strength counts in the weekly load.
"""

from typing import Optional

PHASES = ("base", "build", "peak", "recovery", "taper")

# focus -> card title
FOCI = {
    "heavy-lower": "Strength: heavy lower body",
    "full": "Strength: full body",
    "core-hips": "Strength: core & hips",
    "plyo": "Strength: plyometrics",
    "mobility": "Mobility & prehab",
}
FOCUS_ALIASES = {
    "heavy": "heavy-lower", "lower": "heavy-lower", "heavy-lower": "heavy-lower", "legs": "heavy-lower",
    "full": "full", "full-body": "full", "general": "full",
    "core": "core-hips", "hips": "core-hips", "core-hips": "core-hips", "core-hip": "core-hips",
    "plyo": "plyo", "plyos": "plyo", "plyometrics": "plyo", "reactive": "plyo",
    "mobility": "mobility", "prehab": "mobility",
}
# Estimated TSS per minute of the session, by focus.
TSS_PER_MIN = {"heavy-lower": 0.8, "full": 0.7, "core-hips": 0.5, "plyo": 0.85, "mobility": 0.3}

_WARMUP = "Warm-up 8': easy cardio, then leg swings, hip openers and glute activation."
_COOLDOWN = "Cool-down 5': easy mobility (hips, calves, hamstrings)."

# focus -> phase -> (main set, load / rest)
TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "heavy-lower": {
        "base": ("Goblet squat 3x10 · Romanian deadlift 3x10 · Split squat 3x8/leg · Calf raise 3x15",
                 "RPE 6-7 (3-4 reps in reserve) · rest 90\""),
        "build": ("Back squat 4x5 · Deadlift 3x5 · Bulgarian split squat 3x6/leg · Single-leg calf raise 3x10",
                  "RPE 8 (2 reps in reserve) · rest 2-3'"),
        "peak": ("Back squat 3x3 · Romanian deadlift 2x5 · Split squat 2x6/leg",
                 "RPE 7-8, crisp reps, never to failure · rest 2-3'"),
        "recovery": ("Goblet squat 2x8 · Romanian deadlift 2x8 · Calf raise 2x12",
                     "RPE 6 · rest 90\""),
        "taper": ("Activation: bodyweight squat 2x10 · Glute bridge 2x12 · Calf raise 2x12",
                  "RPE 5, no soreness · rest 60\""),
    },
    "full": {
        "base": ("Goblet squat 3x12 · Push-up 3x10 · Single-leg RDL 3x10/leg · Row 3x12 · Plank 3x40\"",
                 "RPE 6 · rest 60-90\""),
        "build": ("Trap-bar deadlift 4x6 · Step-up 3x8/leg · Overhead press 3x8 · Pull-up 3x6 · Pallof press 3x10/side",
                  "RPE 7-8 · rest 2'"),
        "peak": ("Trap-bar deadlift 3x4 · Step-up 2x6/leg · Pull-up 2x6 · Side plank 2x30\"/side",
                 "RPE 7 · rest 2'"),
        "recovery": ("Goblet squat 2x10 · Push-up 2x10 · Row 2x10 · Plank 2x30\"",
                     "RPE 5-6 · rest 60\""),
        "taper": ("Activation: bodyweight squat 2x10 · Push-up 2x8 · Band row 2x12",
                  "RPE 5 · rest 60\""),
    },
    "core-hips": {
        "base": ("Dead bug 3x10/side · Side plank 3x30\"/side · Clamshell 3x15/side · Glute bridge 3x15 · Copenhagen plank 3x15\"",
                 "Controlled tempo · rest 45\""),
        "build": ("Single-leg glute bridge 3x12/leg · Copenhagen plank 3x25\"/side · Pallof press 3x12/side · Hip airplane 3x6/leg",
                  "Controlled tempo, add load where easy · rest 45\""),
        "peak": ("Side plank 2x30\"/side · Single-leg glute bridge 2x10/leg · Dead bug 2x10/side",
                 "Maintenance · rest 45\""),
        "recovery": ("Dead bug 2x8/side · Side plank 2x20\"/side · Glute bridge 2x12",
                     "Easy · rest 45\""),
        "taper": ("Activation: glute bridge 2x10 · Side plank 2x20\"/side · Clamshell 2x12/side",
                  "Easy, no fatigue · rest 30\""),
    },
    "plyo": {
        "base": ("Pogo jumps 3x15 · Skipping A 3x20 m · Low box jump 3x6 · Lateral hops 3x10",
                 "Quick ground contacts, full recovery · rest 60-90\""),
        "build": ("Pogo jumps 3x20 · Bounding 4x30 m · Box jump 4x5 · Single-leg hops 3x8/leg",
                  "Maximal intent, stop when contacts slow · rest 2'"),
        "peak": ("Pogo jumps 2x15 · Bounding 3x20 m · Box jump 3x4",
                 "Crisp and fast, low volume · rest 2'"),
        "recovery": ("Pogo jumps 2x12 · Skipping A 2x20 m",
                     "Light · rest 60\""),
        "taper": ("Activation: pogo jumps 2x10 · Skipping A 2x15 m",
                  "Light and springy · rest 60\""),
    },
    "mobility": {
        "base": ("Hip flexor stretch 2x45\"/side · 90/90 hip switch 2x8 · Calf/Achilles eccentric 3x15 · Thoracic rotation 2x8/side",
                 "Slow and controlled"),
        "build": ("Hip flexor stretch 2x45\"/side · 90/90 hip switch 2x8 · Calf/Achilles eccentric 3x15 · Hamstring floss 2x10/leg",
                  "Slow and controlled"),
        "peak": ("Hip flexor stretch 2x45\"/side · Calf/Achilles eccentric 2x15 · Thoracic rotation 2x8/side",
                 "Slow and controlled"),
        "recovery": ("Foam roll 5' · Hip flexor stretch 2x45\"/side · 90/90 hip switch 2x8",
                     "Easy"),
        "taper": ("Foam roll 5' · Leg swings 2x10/side · Calf raise 2x10",
                  "Easy"),
    },
}


def phase_key(phase: Optional[str]) -> str:
    """The template phase of a free-text week phase ('Build 2', 'down week', 'race week', ...)."""
    text = str(phase or "").lower()
    for words, key in (
        (("taper", "race"), "taper"),
        (("recover", "down", "deload", "easy week"), "recovery"),
        (("peak", "specific", "sharpen"), "peak"),
        (("build",), "build"),
    ):
        if any(w in text for w in words):
            return key
    return "base"


def focus_key(text: str) -> Optional[str]:
    return FOCUS_ALIASES.get(text.strip().lower())


def strength_session(focus: str, minutes: int, phase: Optional[str]) -> dict:
    """{title, description, summary, tss_planned} of a strength session of `focus` in `phase`."""
    key = phase_key(phase)
    main, load = TEMPLATES[focus][key]
    description = "\n".join([_WARMUP, f"Main: {main}", f"Load: {load}", _COOLDOWN])
    return {
        "title": FOCI[focus],
        "description": description,
        "summary": main,
        "tss_planned": round(minutes * TSS_PER_MIN[focus]),
    }
