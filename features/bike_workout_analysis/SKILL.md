---
name: bike-workout-analysis
description: Power and physiological analysis of one completed ride.
---

# Bike Workout Analysis Skill

## Protocol

1. **Classify** (re-call `analyze_workout(workout_id="<id>")` only if multiple same-day rides are listed and the athlete meant another `[id]`):
   - **Easy / Recovery**: Z1/Z2 spin `< ~90 min`.
   - **Long Ride**: endurance ride `>= ~90 min`.
   - **Structured**: sweet spot, tempo, FTP/threshold, VO2max/sprint, race (`Δ vs target` W is the target source of truth; ignore outdoor weather on indoor trainer rides).

2. **Synthesis** (follow `GOAL REASONING`; use windowed `Pw:Hr` and `EF` as-is):
   - **Power, Drift & Terrain**: evaluate `NP` vs Avg Power, `IF`, `Work (kJ)`, `TSS`, `Pw:Hr` & `EF` (`NP / Avg HR`) against session design + `%FTP` + **Repeated blocks**/laps, and climbing/cadence (grinding vs high-rpm spin).
   - **Readiness & Running Carryover**: weigh execution/RPE/`Work kJ` against Sleep/HRV/RHR and impact-free aerobic benefit vs residual leg fatigue before the next key/long run.

## Output (no `Ride Overview`, no intro/closing prose, do not repeat web-banner stats except to back a judgement)

- **Structured & Long Rides (`<= 200 words`)**:
  1. `### ⚡ Power & Physiological Profile`: 3-4 bullets (`- **Topic:** ...`, `<= 30w`, `⚠️`/`🔴` on issues only) covering `NP`/`IF`/`Work kJ`/`TSS`, step/lap execution (`Δ vs target` W & recovery HR), `EF` & `Pw:Hr` drift, and cadence/terrain.
  2. `### 🧠 Recovery & Readiness Synthesis`: 1-2 bullets (`<= 28w`) weighing Sleep/HRV/RHR and glycogen load against running carryover for current goal & north star.
  3. `### 🚀 Key Takeaways & Adjustments`: 2 numbered directives (`1.`, `2.`, `<= 25w`).
- **Easy & Recovery Rides (`<= 130 words`)**:
  1. `### 🎯 Execution`: 3 bullets (`<= 25w`): **Intensity**, **Aerobic Stability**, **Readiness & Running Carryover** (add **Cadence / Terrain** only when notable).
  2. `### 🚀 Key Takeaways`: 1-2 numbered directives (`<= 20w`).
