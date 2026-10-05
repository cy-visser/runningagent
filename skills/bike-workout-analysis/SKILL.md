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
   - **Classify Ride** (this also selects the output format in step 3):
     - **Easy / Recovery Ride**: active recovery, easy aerobic, or Zone 1/2 spins under ~90 minutes.
     - **Long Ride**: endurance rides ~90 minutes or longer, even when fully Zone 1/2.
     - **Structured Ride**: sweet spot, tempo blocks, FTP/threshold intervals, VO2max/sprint reps, or race efforts.
     - A **Planned structure & execution** section means the ride was built in the TrainingPeaks workout builder: that plan (targets in watts from %FTP) is the source of truth for what was intended. A builder plan alone does not make a ride structured: a single steady Zone 1/2 power target is still an Easy Ride. **Planned session notes** carry the coach's intent.
   - Outdoor weather does not apply to indoor rides. Only discuss room heat/fan cooling if the athlete mentions it (there is no data for it).

2. **Perform Differential Cycling & Physiological Synthesis**:
   - Analyze every ride fully, whatever its type; the step 3 format only controls how much of the analysis is reported.
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
   - Deliver in clean standard Markdown, following the coach's standard plain-text formatting rules (plain `Pw:Hr`, `NP`, `EF`; text arrows `->` or `→`; never LaTeX).
   - **Pick the format from the step 1 classification.** If the athlete explicitly asks for more or less detail, follow that instead.
   - **Structured Rides & Long Rides → Full format:**
     1. **Ride Overview**: Identifying the analyzed cycling session (title, date/time, duration, distance, Work kJ if reported, indoor/outdoor conditions).
     2. **⚡ Power & Physiological Profile**: Objective evaluation of NP, Avg Power, IF, TSS, EF, and `Pw:Hr` aerobic drift status. For structured sessions, summarize interval execution (power stability, HR recovery) in prose here.
     3. **🧠 Recovery & Readiness Synthesis**: Connecting morning recovery indicators (Sleep, HRV, RHR) with ride execution, effort, and fatigue.
     4. **🚀 Actionable Coaching Recommendations**: Specific takeaways covering fueling/hydration, cadence work, or upcoming training adjustments.
   - **Easy & Recovery Rides → Concise format** (short and to the point: Execution + Key Takeaways together under ~120 words):
     1. **Ride Overview**: four bullets, omitting unavailable items: **Date & Title** (plus other same-day sessions, if any); **Volume & Work** (duration | distance | Work kJ | Avg Power / NP); **Physiological Load** (HR avg (max) | cadence | Pw:Hr | EF | TSS / IF); **Environment** (Indoor trainer or outdoor location | conditions, terrain +gain / -loss).
     2. **🎯 Execution**: three one-line bullets, each opening with ✅ (on target), ⚠️ (watch) or ❌ (missed), then the verdict with its key number:
        - **Intensity**: power/HR zone discipline vs. the plan (watt/IF/HR target, if any).
        - **Aerobic stability**: `Pw:Hr` and `EF` with a few words of context (duration, low absolute HR, or conditions).
        - **Readiness**: the morning HRV / RHR / sleep signal (omit if no recovery data).
        - Add a **Cadence / Mechanics** or **Terrain** bullet only when the data shows something notable (e.g. heavy grinding, excessive high-rpm spin at low watts, hilly route). Address athlete feedback (RPE/comment) in the relevant bullet.
        - No physiology explanations, and don't restate Ride Overview numbers unless they carry the verdict.
     3. **🚀 Key Takeaways**: at most 2 numbered one-line directives about what should change in the coming days. Skip generic reminders unless today's data or athlete feedback points to them.
     - Example of the expected length and tone (illustrative values):
       ```
       ### 🎯 Execution
       * ✅ **Intensity:** 120 W avg/NP (55% FTP, IF 0.54) and HR 96 bpm (65% LTHR): true Zone 1/2 recovery spin.
       * ✅ **Aerobic stability:** Pw:Hr 8.0% at 96 bpm avg (~7 bpm rise over 40 min indoors), benign at recovery watts.
       * ✅ **Readiness:** HRV 39 ms and RHR 51 bpm at baseline; 8.2 h sleep.
       * ⚠️ **Cadence:** 99 rpm avg at 120 W adds extra HR cost for an easy spin.

       ### 🚀 Key Takeaways
       1. Drop recovery-spin cadence to 85–90 rpm at 120 W to reduce cardiac drift.
       2. Keep cross-training rides capped at IF 0.55 during peak marathon weeks.
       ```

