---
name: bike-workout-analysis
description: Performs a deep, structured physiological and power analysis of a single completed cycling or indoor biking workout.
---

# Bike Workout Analysis Skill

You are now equipped with the **Bike Workout Analysis** skill. Use this skill whenever the athlete asks to analyze a completed cycling session (e.g., Indoor Cycling, Road Bike, Mountain Bike, Gravel Ride).

## Protocol:

1. **Gather Data**:
   - Call `analyze_workout` (e.g. `analyze_workout(date_str="today", sport="bike")` or `analyze_workout(workout_id="<id>")`). This tool automatically retrieves the completed ride totals, power/HR channels, interval/lap telemetry, morning recovery context (Sleep, HRV, RHR), and outdoor weather in a single call.
   - **Multiple sessions that day**: by date, the tool analyses the day's primary ride (highest load) and lists any other completed sessions with their ids at the top. If the runner clearly meant a different session, re-call `analyze_workout(workout_id="<id>")`; otherwise briefly acknowledge the other sessions as context.
   - A **Planned structure & execution** section means the ride was built in the TrainingPeaks workout builder: that plan (targets in watts from %FTP) is the source of truth for what was intended. **Planned session notes** carry the coach's intent.
   - Outdoor weather does not apply to indoor rides. Only discuss room heat/fan cooling if the athlete mentions it (there is no data for it).

2. **Perform Differential Cycling & Physiological Synthesis**:
   - **Power Output & Intensity Classification**:
     - Evaluate **Normalized Power (NP)** vs. **Average Power**, **Intensity Factor (IF)**, total **Work (kJ)** when the totals report it, and **Training Stress Score (TSS)**.
     - Classify ride type: Active Recovery / Easy Aerobic (Zone 1/2 Power), Sweet Spot / Tempo Block, Functional Threshold Power (FTP) / Threshold Intervals, or High-Intensity VO2max / Sprint reps.
   - **Aerobic Decoupling (`Pw:Hr`) & Efficiency Factor (`EF`)**:
     - Examine `Pw:Hr` (the ratio of power output stability against heart rate drift over the ride) contextually alongside temperature, duration, and fueling. Decoupling indicates cardiovascular drift from glycogen depletion, dehydration, or indoor thermal strain.
     - Evaluate `EF` (`NP / Average HR`) to track cardiovascular cycling efficiency trends over time.
     - **Reason about drift; don't apply fixed cut-offs.** The tool excludes the first 5 minutes of every session (and the planned warm-up/cool-down for builder workouts); each value's label states its window and duration. Do not recompute or quote a whole-session value. Weigh the value against:
       - **Session design**: continuous efforts (steady endurance or tempo blocks, alternations without full recovery such as over-unders) naturally accumulate HR creep; separate reps with full recovery should show little rep-to-rep drift.
       - **Intensity relative to threshold** (drift grows with intensity), and the **window duration** (short windows are noisier).
       - **Conditions** (heat, humidity, wind, terrain) and **readiness** (sleep, HRV, RHR trend; fueling/hydration if mentioned).
       - Literature reference points (e.g. Friel's ~5% for steady aerobic efforts, ~3.5% in aerobic-threshold tests) can inform the reasoning but are not verdicts.
   - **Elevation & Climbing Profile**:
     - Evaluate total elevation gain/loss (+Xm / -Ym), climbing VAM (Vertical Ascent Meters/hour), and climbing power vs flat power.
     - Correlate power surges and cadence/torque shifts with road gradient and climbing sections.
   - **Cadence & Mechanics**:
     - Analyze average and peak cadence (rpm). Identify torque vs. cadence imbalances (e.g. low-cadence heavy grinding vs. high-cadence neuromuscular spin).
   - **Physiological Recovery & Readiness Context**:
     - Synthesize the ride execution against morning recovery metrics from `analyze_workout`:
       - Did low morning HRV or elevated Resting Heart Rate (RHR) correspond with exaggerated HR drift (`Pw:Hr`) or a high RPE / low feeling score in the **Athlete feedback** line?
       - Was sleep duration adequate to support the glycogen demand and metabolic workload of the session (use Work kJ if reported)?
   - **Lap & Interval Breakdown**:
     - If a **Planned structure & execution** section is present, judge each step against its planned watts (the Check column) and use the **Repeated blocks** summary and the per-block `Pw:Hr` (`[key block]`) for interval execution.
     - Otherwise analyze structured work intervals versus recovery laps for average/max power stability, heart rate response, recovery lap HR drop, and pedal cadence consistency.

3. **Deliver Bike Workout Summary**:
   - Deliver in clean standard Markdown, following the coach's standard plain-text formatting rules (plain `Pw:Hr`, `NP`, `EF`; text arrows `->` or `→`; never LaTeX):
     1. **Ride Overview**: Identifying the analyzed cycling session (title, date/time, duration, distance, Work kJ if reported, indoor/outdoor conditions).
     2. **⚡ Power & Physiological Profile**: Objective evaluation of NP, Avg Power, IF, TSS, EF, and `Pw:Hr` aerobic drift status. For structured sessions, summarize interval execution (power stability, HR recovery) in prose here.
     3. **🧠 Recovery & Readiness Synthesis**: Connecting morning recovery indicators (Sleep, HRV, RHR) with ride execution, effort, and fatigue.
     4. **🚀 Actionable Coaching Recommendations**: Specific takeaways covering fueling/hydration, cadence work, or upcoming training adjustments.
