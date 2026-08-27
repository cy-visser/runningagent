---
name: workout-analysis
description: Performs a deep, structured physiological analysis of a single completed workout/run.
---

# Workout Analysis Skill

You are now equipped with the Workout Analysis skill. Use this skill when the runner asks to analyze a specific **run** or **running workout**. *(Note: For completed cycling/biking workouts, route to the `bike-workout-analysis` skill.)*

## Protocol:

1. **Gather Data**:
   - Call `analyze_workout` (e.g. `analyze_workout(date_str="today")` or `analyze_workout(workout_id="<id>")`). This tool automatically retrieves the completed workout telemetry, interval/lap data, morning physiological recovery metrics (Sleep, HRV, RHR), and run-time environmental weather in a single call.
   - **Classify Workout**: Determine from the telemetry if the run is an **Easy Run** vs. a **Structured Workout** (intervals, tempo, threshold, race, progressive, push, MP block, reps).

2. **Perform Differential Physiological Synthesis**:
   - **For Easy & Recovery Runs**:
     - Evaluate low-intensity compliance (holding heart rate in Zone 1/2), overall pace/HR stability, and cardiac drift across the duration.
     - Look for 'gray zone' (Zone 3/4) creep where recovery runs are executed too fast, compromising metabolic recovery.
     - Reference lap data if pacing surges or significant cardiac drift are present across splits.
   - **For Structured Workouts (Intervals, Tempo, Threshold, Race, Progressive, MP Blocks, Reps)**:
     - Analyze lap data (`lapData`): evaluate individual work intervals vs. recovery laps for pacing consistency (even/negative splits vs. fading), heart rate response, recovery lap HR drop, and cadence stability.
   - **Elevation & Terrain Impact**:
     - Evaluate total elevation gain/loss (+Xm / -Ym), route gradient, and climbing rate (VAM).
     - Compare **Normalized Graded Pace (NGP)** against raw pace: understand that slower raw pace on uphill segments with steady NGP/HR indicates consistent effort and good pacing discipline rather than fatigue or aerobic decoupling.
     - Assess biomechanical adaptations to grade (cadence adjustments, stride length changes on climbs vs. descents).
   - **Aerobic Decoupling & Weather Context**:
     - Synthesize `Pa:Hr` (pace vs. heart rate drift) contextually with run-time environmental conditions (temperature, humidity, solar radiation, wind). Distinguish expected thermoregulatory cardiac drift in high heat/humidity from poor pacing or cardiovascular fatigue in moderate conditions.
   - **Physiological Recovery & Readiness Context**:
     - Cross-reference run execution against morning recovery metrics from `analyze_workout` (Sleep duration, HRV baseline stability, and Resting Heart Rate trends) to assess readiness and strain.
   - **Goal Alignment**: Connect the run execution to long-term goal pacing and phase progression.

3. **Deliver Workout Summary**:
   - Deliver an objective, data-backed assessment in clean standard Markdown:
     - Plain-Text Metrics & Progressions: Write metrics as plain text (e.g. `Pa:Hr`, `Pw:Hr`, `NGP`, `HR 155 bpm`, `4:30/km`) and use standard text arrows (`->` or `→`) for lap progressions. Never wrap metrics or symbols in LaTeX math formatting (e.g. do not write `$\rightarrow$` or `$P_a:HR$`).
     1. **Session Overview**: Date, sport, title, distance, duration, and environmental conditions.
     2. **🎯 Execution & Physiological Assessment**: Honest, data-backed critique of what was executed well vs. breakdowns (e.g. pacing control, Zone 1/2 discipline, Pa:Hr drift context, terrain management, and recovery state).
     3. **⏱️ Lap & Interval Breakdown**: Lap-by-lap breakdown of work vs. recovery splits and heart rate dynamics for structured sessions (or when pacing/drift warrants split inspection).
     4. **🚀 Key Takeaways & Adjustments**: Specific, actionable coaching directives for upcoming workouts and recovery.