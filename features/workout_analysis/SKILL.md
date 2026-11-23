---
name: workout-analysis
description: Telemetry and physiological analysis of one completed run.
---

# Workout Analysis Skill

## Protocol

1. **Classify** (re-call `analyze_workout(workout_id="<id>")` only if multiple same-day runs are listed and the runner meant another `[id]`):
   - **Easy / Recovery**: easy, recovery, aerobic, shakeout (strides included).
   - **Long Run**: titled long run or `>= ~90 min`.
   - **Structured**: intervals, tempo, threshold, race, progressive, MP blocks (**Planned structure & execution** `Δ vs target`: `0` = in range, negative pace = faster).

2. **Synthesis** (follow `GOAL REASONING`; use windowed `Pa:Hr` and aligned deltas as-is—never recompute):
   - **Easy / Recovery**: Z1/Z2 HR compliance, Z3/Z4 creep, surges, drift.
   - **Structured / Long**: **Repeated blocks** + per-block decoupling or **Laps Breakdown** (consistency, HR recovery drops, rep-to-rep GCT/VR/cadence drift); separate quality blocks from easy km on quality LRs.
   - **Running Dynamics (signal-only)**: inspect **Running Dynamics** and `Late-run drift` (weigh runner height & injury watchpoints). Mention mechanics **ONLY** when `Late-run drift` flags late-run mechanical fatigue (rising GCT/VR, cadence drop, or stride collapse at equal/slower pace), rep-to-rep form fade shows up, or a concrete cadence/stride/overstriding limiter appears (e.g., high VR + long GCT at easy pace, or cadence/stride bottleneck on quality reps). **NEVER** write obvious filler like "cadence is ok", "stride length is good", or "form looks solid"—the banner already shows the numbers.
   - **Terrain, Drift & Readiness**: weigh elevation/grade/`NGP` vs raw pace, `Pa:Hr` against session design + weather, and Sleep/HRV/RHR. On a **Sub-goal race**, congratulate, frame via north-star equivalent/gap, and note if the result was saved.

## Output (no `Session Overview`, no intro/closing prose, do not repeat web-banner stats except to back a judgement)

- **Structured & Long Runs (`<= 210 words`)**:
  1. `### 🎯 Execution & Physiological Assessment`: 4-5 bullets (`- **Topic:** ...`, `<= 30w`, `⚠️`/`🔴` on issues only): **Pacing & Target Discipline**, **Interval & Recovery Dynamics**, **Aerobic Stability & Conditions**, **Readiness & Load Absorption**, **Goal & North-Star Impact**.
  2. `### 🚀 Key Takeaways & Adjustments`: 2 numbered directives (`1.`, `2.`, `<= 25w`) with concrete target numbers.
- **Easy & Recovery Runs (`<= 130 words`)**:
  1. `### 🎯 Execution`: 3 bullets (`<= 25w`): **Intensity & Pacing**, **Aerobic Stability**, **Readiness** (omit if absent; add **Mechanics / Terrain** only when notable).
  2. `### 🚀 Key Takeaways`: 1-2 numbered directives (`<= 20w`).
