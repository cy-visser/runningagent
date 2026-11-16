---
name: workout-analysis
description: Telemetry and physiological analysis of one completed run.
---

# Workout Analysis Skill

## Protocol

1. **Classify Run** (re-call `analyze_workout(workout_id="<id>")` only if multiple same-day sessions are listed and the runner meant another `[id]`; otherwise note same-day sessions in one brief clause):
   - **Easy / Recovery Run**: easy, recovery, aerobic, shakeout (strides included; a single steady easy-pace builder block stays Easy).
   - **Long Run**: titled long run or >= ~90 min, even when fully easy.
   - **Structured Workout**: intervals, tempo, threshold, race, progressive, MP blocks, reps (**Planned structure & execution** + **Planned session notes** define intended targets; `Δ vs target`: `0` = in range, negative pace = faster).

2. **Physiological Synthesis**:
   - **Easy / Recovery**: check Zone 1/2 HR compliance, gray-zone (Zone 3/4) creep, split surges, and cardiac drift.
   - **Structured / Long**: judge execution from **Repeated blocks** and per-block decoupling (`[highest target intensity]`), or **Laps Breakdown** (split consistency, HR recovery drops, cadence); on race-pace long runs, separate the quality block from easy km.
   - **Terrain & `NGP`**: evaluate elevation (`+Xm / -Ym`), grade, VAM, and `NGP` vs raw pace (steady `NGP`/HR on climbs = disciplined effort, not fade) plus cadence/stride changes.
   - **Decoupling (`Pa:Hr`) & Readiness**: use the tool's windowed `Pa:Hr` as-is (never recompute whole-session drift). Judge contextually against session design (continuous/Canova vs full-recovery reps), intensity, window length, weather, and morning Sleep/HRV/RHR.
   - **Goals & Races**: connect to `GOAL REASONING`. On a **Sub-goal race**, congratulate, frame via north-star equivalent/gap, and note in one sentence if the result was saved. On a non-goal race (parkrun/tune-up) when tools are enabled, call `record_key_event(event_type="race", ...)` alongside your summary.

3. **Output Format**:
   - Keep internal reasoning brief—do not re-sum splits, walk row-by-row through aligned tables, or draft prose in thoughts; use the pre-computed deltas and decoupling directly.
   - The web banner already displays title, distance, duration, pace/NGP, HR zones, decoupling, readiness, and weather—**write NO `Session Overview` section, write no intro/closing prose, and do not repeat banner stats** except numbers needed to back a judgement.
   - Prefix genuine execution, drift, gray-zone, or recovery issues with `- ⚠️ **Topic:**` or `- 🔴 **Topic:**`, leaving solid/normal bullets unmarked:
   - **Structured Workouts & Long Runs (<= 210 words total)**:
     1. `### 🎯 Execution & Physiological Assessment`: 4-5 concise bullets (`- **Topic:** ...`, <= 30 words each) covering: **Pacing & Target Discipline** (`Δ vs target`, spread, cadence/stride), **Interval & Recovery Dynamics** (HR climb across reps, recovery-jog pace & HR drop, or quality vs easy separation), **Aerobic Stability & Conditions** (windowed/block `Pa:Hr` in terrain/weather context), **Readiness & Load Absorption** (HRV/RHR/sleep vs `rTSS`/RPE and same-day sessions), and **Goal & North-Star Impact**.
     2. `### 🚀 Key Takeaways & Adjustments`: 2 numbered directives (`1.`, `2.`, <= 25 words each) with concrete target numbers and brief rationale.
   - **Easy & Recovery Runs (<= 130 words total)**:
     1. `### 🎯 Execution`: 3 concise bullets (`- **Topic:** ...`, <= 25 words each): **Intensity & Pacing** (zone/plan compliance), **Aerobic Stability** (`Pa:Hr` in weather/terrain context), and **Readiness** (HRV/RHR/sleep + same-day/prior load, omit if absent; add **Mechanics / Terrain** only when notable).
     2. `### 🚀 Key Takeaways`: 1-2 numbered directives (`1.`, `2.`, <= 20 words each) for upcoming days.
