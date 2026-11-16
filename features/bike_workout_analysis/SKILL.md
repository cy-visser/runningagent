---
name: bike-workout-analysis
description: Power and physiological analysis of one completed ride.
---

# Bike Workout Analysis Skill

## Protocol

1. **Classify Ride** (re-call `analyze_workout(workout_id="<id>")` only if multiple same-day rides are listed and the athlete meant another `[id]`):
   - **Easy / Recovery Ride**: Z1/Z2 spin < ~90 min (even if built as a single steady builder block).
   - **Long Ride**: endurance ride >= ~90 min.
   - **Structured Ride**: sweet spot, tempo, FTP/threshold, VO2max/sprint, race (**Planned structure & execution** `Δ vs target` in W is the target source of truth).
   - Ignore outdoor weather on indoor trainer rides (mention room cooling only if raised).

2. **Cycling & Physiological Synthesis**:
   - **Power & Work**: evaluate `NP` vs Avg Power, `IF`, `Work (kJ)` (when present), and `TSS`.
   - **Decoupling (`Pw:Hr`) & `EF`**: use the tool's windowed `Pw:Hr` and `EF` (`NP / Avg HR`) as-is; judge contextually against session design (steady/over-unders vs full-recovery reps), `%FTP`, duration, low absolute recovery HR, conditions/fueling, and **Repeated blocks** (`[highest target intensity]`) or **Laps Breakdown**.
   - **Terrain & Cadence**: correlate climbing (`+Xm / -Ym`, VAM) and torque/cadence (rpm—heavy grinding vs high-rpm spin) with power stability.
   - **Readiness & Running Goals**: weigh execution and athlete RPE/feedback against morning Sleep/HRV/RHR (`Work kJ` glycogen demand), and state what the ride means for the runner's current goal and north star (impact-free aerobic load vs residual leg fatigue before the next key/long run).

3. **Output Format**:
   - Keep internal reasoning brief—do not re-walk aligned step rows or draft prose in thoughts.
   - The web banner already displays title, duration, distance, power/NP, HR, IF/TSS, Pw:Hr, readiness, and conditions—**write NO `Ride Overview` section, write no intro/closing prose, and do not repeat banner stats** except numbers needed to back a judgement.
   - Prefix genuine power/pacing, drift, fueling, or fatigue issues with `- ⚠️ **Topic:**` or `- 🔴 **Topic:**`, leaving solid/normal bullets unmarked:
   - **Structured Rides & Long Rides (<= 200 words total)**:
     1. `### ⚡ Power & Physiological Profile`: 3-4 concise bullets (`- **Topic:** ...`, <= 30 words each) covering `NP`/Avg Power/`IF`/`Work kJ`/`TSS`, interval/lap execution (`Δ vs target` W and recovery HR), `EF` & `Pw:Hr` drift in context, and cadence/torque + terrain.
     2. `### 🧠 Recovery & Readiness Synthesis`: 1-2 concise bullets (<= 28 words each) weighing Sleep/HRV/RHR and glycogen load against running carryover for the current goal and north star.
     3. `### 🚀 Key Takeaways & Adjustments`: 2 numbered directives (`1.`, `2.`, <= 25 words each) on fueling/hydration, cadence, or upcoming run/ride adjustments.
   - **Easy & Recovery Rides (<= 130 words total)**:
     1. `### 🎯 Execution`: 3 concise bullets (`- **Topic:** ...`, <= 25 words each): **Intensity** (watt/IF/HR compliance), **Aerobic Stability** (`Pw:Hr` & `EF` in context), and **Readiness & Running Carryover** (HRV/RHR/sleep + leg freshness before next run; add **Cadence / Terrain** only when notable).
     2. `### 🚀 Key Takeaways`: 1-2 numbered directives (`1.`, `2.`, <= 20 words each) for upcoming days.
