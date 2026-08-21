---
name: bike-workout-analysis
description: Performs a deep, structured physiological and power analysis of a single completed cycling or indoor biking workout.
---

# Bike Workout Analysis Skill

You are now equipped with the **Bike Workout Analysis** skill. Use this skill whenever the athlete asks to analyze a completed cycling session (e.g., Indoor Cycling, Road Bike, Mountain Bike, Gravel Ride).

## Protocol:

1. **Gather Data**:
   - Call `analyze_workout` (e.g. `analyze_workout(date_str="today")` or `analyze_workout(workout_id="<id>")`). This tool automatically retrieves the completed ride totals, power/HR channels, interval/lap telemetry, morning recovery context (Sleep, HRV, RHR), and outdoor weather in a single call.
   - For indoor rides, evaluate room environment and airflow context (e.g. thermal stress/fan cooling).

2. **Perform Differential Cycling & Physiological Synthesis**:
   - **Power Output & Intensity Classification**:
     - Evaluate **Normalized Power (NP)** vs. **Average Power**, **Intensity Factor (IF)**, total work executed in **Kilojoules (kJ)**, and **Training Stress Score (TSS)**.
     - Classify ride type: Active Recovery / Easy Aerobic (Zone 1/2 Power), Sweet Spot / Tempo Block, Functional Threshold Power (FTP) / Threshold Intervals, or High-Intensity VO2max / Sprint reps.
   - **Aerobic Decoupling (`Pw:Hr`) & Efficiency Factor (`EF`)**:
     - Examine `Pw:Hr` (the ratio of power output stability against heart rate drift over the ride). An aerobic drift > 5% indicates glycogen depletion, thermal accumulation/dehydration, or indoor heat buildup.
     - Evaluate `EF` (`NP / Average HR`) to track cardiovascular cycling efficiency trends over time.
   - **Cadence & Mechanics**:
     - Analyze average and peak cadence (rpm). Identify torque vs. cadence imbalances (e.g. low-cadence heavy grinding vs. high-cadence neuromuscular spin).
   - **Physiological Recovery & Readiness Context**:
     - Synthesize the ride execution against morning recovery metrics from `analyze_workout`:
       - Did low morning HRV or elevated Resting Heart Rate (RHR) correspond with exaggerated HR drift (`Pw:Hr`) or high rating of perceived effort?
       - Was sleep duration adequate to support the glycogen demand and metabolic workload (kJ) of the session?
   - **Lap & Interval Breakdown**:
     - Analyze structured work intervals versus recovery laps for average/max power stability, heart rate response, recovery lap HR drop, and pedal cadence consistency.

3. **Deliver Bike Workout Summary**:
   - Always use clean plain text and standard Markdown for numbers, units, transitions, and metrics. Never use LaTeX syntax or dollar-sign delimiters (`$...$`).
   - Structure your response using these concise sections:
     1. **Warm Greeting & Ride Overview**: Identifying the analyzed cycling session (title, date/time, duration, distance, total work in kJ).
     2. **⚡ Power & Effort Profile**: Concise table or bullets with NP, Avg Power, IF, TSS, EF, and `Pw:Hr` aerobic drift status.
     3. **🧠 Physiological & Recovery Synthesis**: Connecting morning recovery indicators (Sleep, HRV, RHR) with ride effort and aerobic drift.
     4. **⏱️ Interval & Lap Breakdown** *(include only for structured interval/sweet spot/tempo workouts)*: Lap-by-lap comparison of target power vs actual power and heart rate recovery.
     5. **🚀 Actionable Coaching Recommendations**: 2-3 specific takeaways covering fueling/hydration, cadence work, or upcoming training adjustments.
