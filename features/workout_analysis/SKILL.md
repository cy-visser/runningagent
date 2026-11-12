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

3. **Output Format**:
   - **Structured Workouts & Long Runs (Full)**:
     1. **Session Overview**: date, sport, title, distance, duration, conditions.
     2. **🎯 Execution & Physiological Assessment**: pacing/zone discipline, interval/block execution in prose, `Pa:Hr` + weather/terrain (`NGP`) + readiness synthesis, goal impact.
     3. **🚀 Key Takeaways & Adjustments**: concrete next-session and recovery directives.
   - **Easy & Recovery Runs (Concise — Execution + Takeaways <= ~120 words, no physiology lectures or repeated overview stats)**:
     1. **Session Overview**: up to 4 bullets (omit missing): **Date & Title** (+ same-day sessions); **Volume** (distance | duration | pace (NGP)); **Physiological Load** (HR avg (max) | cadence | Pa:Hr | rTSS); **Environment** (location | temp (feels like), humidity, wind, +gain / -loss).
     2. `### 🎯 Execution`: 3 one-line bullets starting with `✅` / `⚠️` / `❌` + key metric: **Intensity** (zone/plan compliance), **Aerobic stability** (`Pa:Hr` in context), **Readiness** (HRV/RHR/sleep, omit if absent), plus optional **Mechanics** / **Terrain** only when notable; weave RPE/comments into the relevant bullet.
     3. `### 🚀 Key Takeaways`: 1-2 numbered one-line directives for upcoming days (no generic reminders).
