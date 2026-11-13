---
name: bike-workout-analysis
description: Physiological and power analysis of a single completed indoor or outdoor cycling workout.
---

# Bike Workout Analysis Skill

## Protocol

1. **Gather & Classify**:
   - Call `analyze_workout(date_str="today", sport="bike")` or `analyze_workout(workout_id="<id>")` in the same step as `load_skill`. Re-call by `workout_id` only if the athlete meant another listed same-day ride.
   - Classify ride (selects step 3 format unless asked otherwise):
     - **Easy / Recovery Ride**: Z1/Z2 spin < ~90 min (even if built as a single steady builder block).
     - **Long Ride**: endurance ride >= ~90 min.
     - **Structured Ride**: sweet spot, tempo, FTP/threshold, VO2max/sprint, race (**Planned structure & execution** `Δ vs target` in W is the target source of truth).
   - Ignore outdoor weather on indoor trainer rides (mention room cooling only if the athlete raised it).

2. **Cycling & Physiological Synthesis**:
   - **Power & Work**: evaluate `NP` vs Avg Power, `IF`, `Work (kJ)` (when present), and `TSS`.
   - **Decoupling (`Pw:Hr`) & `EF`**: use the tool's windowed `Pw:Hr` and `EF` (`NP / Avg HR`) as-is; judge contextually against session design (steady/over-unders vs full-recovery reps), `%FTP`, duration, low absolute recovery HR, conditions/fueling, and **Repeated blocks** (`[highest target intensity]`) or **Laps Breakdown**.
   - **Terrain & Cadence**: correlate climbing (`+Xm / -Ym`, VAM) and torque/cadence (rpm—heavy grinding vs high-rpm spin) with power stability.
   - **Readiness & Running Goals**: weigh execution and athlete RPE/feedback against morning Sleep/HRV/RHR (`Work kJ` glycogen demand), and state what the ride means for the runner's current goal and north star (impact-free aerobic load vs residual leg fatigue before the next key/long run).

3. **Output Format** (no physiology lectures or repeated banner stats; prefix genuine power/pacing, drift, fueling, or fatigue issues with `- ⚠️ **Topic:**` or `- 🔴 **Topic:**`, leaving solid/normal bullets unmarked):
   - **Structured Rides & Long Rides (Analysis + Takeaways ~180–280 words)**:
     1. `### Ride Overview`: up to 4 compact bullets (**Date & Title**, **Volume & Work**, **Physiological Load**, **Environment**).
     2. `### ⚡ Power & Physiological Profile`: 3-4 analytical bullets (`- **Topic:** ...`, 1-2 fuller sentences / ~35-50 words each) covering `NP`/Avg Power/`IF`/`Work kJ`/`TSS`, interval/lap execution (`Δ vs target` W and recovery HR), `EF` & `Pw:Hr` drift in context, and cadence/torque + terrain.
     3. `### 🧠 Recovery & Readiness Synthesis`: 1-2 bullets (1-2 sentences each) weighing Sleep/HRV/RHR and glycogen load against running carryover for the current goal and north star.
     4. `### 🚀 Key Takeaways & Adjustments`: 2-3 numbered directives (`1.`, `2.`, 1-2 concise sentences / ~20-35 words each) on fueling/hydration, cadence, or upcoming run/ride adjustments.
   - **Easy & Recovery Rides (Execution + Takeaways ~120–160 words)**:
     1. `### Ride Overview`: up to 4 bullets (omit missing): **Date & Title** (+ same-day sessions); **Volume & Work** (duration | distance | Work kJ | Avg Power / NP); **Physiological Load** (HR avg (max) | cadence | Pw:Hr | EF | TSS / IF); **Environment** (Indoor trainer or location | conditions, +gain / -loss).
     2. `### 🎯 Execution`: 3-4 concise bullets (`- **Topic:** ...`, 1-2 short sentences / ~25-35 words each): **Intensity** (watt/IF/HR compliance), **Aerobic Stability** (`Pw:Hr` & `EF` in context), **Readiness & Running Carryover** (HRV/RHR/sleep + leg freshness before next run, omit if absent), plus optional **Cadence / Terrain** only when notable.
     3. `### 🚀 Key Takeaways`: 1-2 numbered concise directives (`1.`, `2.`) for upcoming days.
