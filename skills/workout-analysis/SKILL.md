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
   - **For Easy Runs**:
     - Do NOT analyze lap data.
     - Evaluate low-intensity compliance (keeping HR strictly in Zone 1/2), overall pace/HR stability, aerobic decoupling (Pa:Hr), biometrics (cadence/stance time stability), and recovery/goal alignment.
   - **For Structured Workouts (Intervals, Tempo, Threshold, Race, Progressive, Push, MP Blocks, Reps)**:
     - REQUIRES lap data analysis (`lapData`).
     - Analyze individual work intervals vs. recovery laps for pace consistency, average/max HR, HR drop during recovery laps, and pace stability during MP blocks.
   - **Aerobic Decoupling & Weather**: Evaluate Pa:Hr across environmental conditions (temp, humidity, wind).
   - **Physiological Recovery & Readiness Context**: Cross-reference run execution against morning recovery metrics from `analyze_workout` (Sleep duration, HRV baseline stability, and Resting Heart Rate trends) to assess readiness and strain.
   - **Biometrics & Injury Alignment**: Correlate biomechanics and HR drift with profile injuries to detect compensation patterns.
   - **Goal Alignment**: Connect the run execution to long-term goal pacing.

3. **Deliver Workout Summary**:
   - Format response with standard sections:
     1. **Warm Note**: Identifying analyzed workout.
     2. **🌟 Workout Highlights**: 1-2 bullet points celebrating execution.
     3. **⏱️ Lap & Interval Breakdown (ONLY for Structured Workouts)**: Detailed interval vs. recovery lap analysis. (Omitted for Easy Runs).
     4. **🚀 Key Takeaways & Recommendations**: 1-2 actionable coaching insights relating execution to long-term goals.