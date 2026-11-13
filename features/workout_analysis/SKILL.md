---
name: workout-analysis
description: Deep physiological and telemetry analysis of a single completed running workout.
---

# Workout Analysis Skill

## Protocol

1. **Gather & Classify**:
   - Call `analyze_workout(date_str="today", sport="run")` or `analyze_workout(workout_id="<id>")` in the same step as `load_skill`. If multiple sessions exist on that day and the runner meant another listed `[id]`, re-call with `workout_id`; otherwise note same-day sessions briefly.
   - Classify the run (selects step 3 format unless the runner asks for more/less detail):
     - **Easy / Recovery Run**: easy, recovery, aerobic, shakeout (strides included; a single steady easy-pace builder block stays Easy).
     - **Long Run**: titled long run or >= ~90 min, even when fully easy.
     - **Structured Workout**: intervals, tempo, threshold, race, progressive, MP blocks, reps. **Planned structure & execution** + **Planned session notes** define intended targets (`Δ vs target`: `0` = in range, negative pace = faster).

2. **Physiological Synthesis**:
   - **Easy / Recovery**: check Zone 1/2 HR compliance, gray-zone (Zone 3/4) creep, split surges, and cardiac drift.
   - **Structured / Long**: judge execution from **Repeated blocks** and per-block decoupling (`[highest target intensity]`), or **Laps Breakdown** (split consistency, HR recovery drops, cadence); on race-pace long runs, separate the quality block from easy km.
   - **Terrain & `NGP`**: evaluate elevation (`+Xm / -Ym`), grade, VAM, and `NGP` vs raw pace (steady `NGP`/HR on climbs = disciplined effort, not fade) plus cadence/stride changes.
   - **Decoupling (`Pa:Hr`) & Readiness**: use the tool's windowed `Pa:Hr` as-is (never recompute whole-session drift). Judge contextually against session design (continuous/Canova vs full-recovery reps), intensity, window length, weather (temp, feels-like, humidity, wind), and morning Sleep/HRV/RHR.
   - **Goals & Races**: connect to `GOAL REASONING`. On a **Sub-goal race**, congratulate, frame via north-star equivalent/gap, and note in one sentence if the result was saved. On a non-goal race (parkrun/tune-up) when tools are enabled, call `record_key_event(event_type="race", ...)` alongside your summary.

3. **Output Format** (no physiology lectures or repeated banner stats; prefix genuine execution, drift, gray-zone, or recovery issues with `- ⚠️ **Topic:**` or `- 🔴 **Topic:**`, leaving solid/normal bullets unmarked):
   - **Structured Workouts & Long Runs (Execution + Takeaways ~180–280 words)**:
     1. `### Session Overview`: up to 4 compact bullets (**Date & Title**, **Volume**, **Physiological Load**, **Environment**).
     2. `### 🎯 Execution & Physiological Assessment`: 4-5 analytical bullets (`- **Topic:** ...`, 1-2 fuller sentences / ~35-50 words each) covering:
        - **Pacing & Target Discipline** (rep/block splits, spread, `Δ vs target`, cadence/stride mechanics),
        - **Interval & Recovery Dynamics** (HR climb across reps, recovery-jog pace & HR drop, or quality-block vs easy-km separation on long runs),
        - **Aerobic Stability & Conditions** (windowed/block `Pa:Hr` weighed against session structure, `NGP`/elevation/VAM, and weather),
        - **Readiness & Load Absorption** (HRV/RHR/sleep trend vs `rTSS`/RPE and same-day sessions), and
        - **Goal & North-Star Impact** (what this session proves or builds for the active block and north star).
     3. `### 🚀 Key Takeaways & Adjustments`: 2-3 numbered directives (`1.`, `2.`, 1-2 concise sentences / ~20-35 words each) with concrete target numbers and brief rationale.
   - **Easy & Recovery Runs (Execution + Takeaways ~120–160 words)**:
     1. `### Session Overview`: up to 4 bullets (omit missing): **Date & Title** (+ same-day sessions); **Volume** (distance | duration | pace (NGP)); **Physiological Load** (HR avg (max) | cadence | Pa:Hr | rTSS); **Environment** (location | temp (feels like), humidity, wind, +gain / -loss).
     2. `### 🎯 Execution`: 3-4 concise bullets (`- **Topic:** ...`, 1-2 short sentences / ~25-35 words each): **Intensity & Pacing** (zone/plan compliance), **Aerobic Stability** (`Pa:Hr` in weather/terrain context), **Readiness** (HRV/RHR/sleep + prior-day load, omit if absent), plus optional **Mechanics / Terrain** only when notable; weave RPE/comments into the relevant bullet.
     3. `### 🚀 Key Takeaways`: 1-2 numbered concise directives (`1.`, `2.`) for upcoming days (no generic reminders).
