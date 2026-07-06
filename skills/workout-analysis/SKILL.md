---
name: workout-analysis
description: Performs a deep, structured physiological analysis of a single completed workout/run.
---

# Workout Analysis Skill

You are now equipped with the Workout Analysis skill. Use this skill when the runner asks to analyze a specific run or workout (e.g., "Analyze today's run", "How was my workout yesterday?").

## Protocol:
1.  **Gather Data**:
    *   Call the `fetch_runner_status` tool for the specific date of the workout to find the workout ID and basic details (or use the current date if the user asks for "today's run").
    *   Once you have the `workout_id` from the summary, call the `analyze_workout` tool with that `workout_id`. This will retrieve full detailed logs, lap data, pace/heart rate/cadence/power averages, and zones.
    *   Call the `get_weather_for_dates` tool, passing the run's start time timestamp (e.g., `'2026-07-02T07:40:05'`) to get the exact weather at the time of the run.
2.  **Perform Physiological Analysis**:
    *   **Intensity Compliance**: Assess whether the runner's heart rate stayed within the planned zones (e.g., Zone 1 for easy runs).
    *   **Aerobic Efficiency**: Check relationship between Pace and Heart Rate (Aerobic Decoupling / Pa:Hr). Identify if decoupling was under 5% (stable) or above (drift), and explain why (e.g., heat, wind, fatigue).
    *   **Biometrics**: Review cadence (aiming for 170-175+ spm to minimize impact), step length, and stance time.
    *   **Injury Alignment**: Correlate biomechanics and heart rate drift with any injuries listed in their profile (e.g., calf injury recovery).
    *   **Goal Alignment**: Connect today's run to their long-term training goal (e.g. NYC Marathon) and declare progress.
3.  **Deliver a Structured Report**:
    *   Format the report exactly using the Markdown Template below.
    *   Do NOT print the full report in the chat.
    *   You MUST call the `save_report_to_artifacts` tool to save and render the report in the Artifacts pane (use filename `workout_analysis_report.md`).
    *   In the chat, provide a brief summary of the key findings and let them know the full report is available for more details.

## Mandatory Report Template:

# Workout Analysis: [Workout Title] ([Date])

### 1. Workout Overview
- **Date**: [Date, e.g. July 2, 2026]
- **Title**: [Workout Title, e.g. 6km Easy Run]
- **Distance**: [Actual Distance, e.g. 6.27 km] (Planned: [Planned Distance, e.g. 6.00 km])
- **Duration**: [Elapsed Time / Duration in MM:SS or HH:MM:SS, e.g. 37:37]
- **Average Pace**: [Average Pace, e.g. 6:02 min/km]
- **Average Heart Rate**: [Avg HR, e.g. 138 bpm] (Max: [Max HR, e.g. 152 bpm])
- **Total Elevation Gain**: [Elevation Gain, e.g. 10 m]
- **Cadence**: [Cadence, e.g. 172 spm]

### 2. Environmental Factors & Stress Correlation
- **Run Time**: [Start Time, e.g. 07:40 AM]
- **Temperature**: [Temperature Range at run time, e.g. ~18.4°C - 19.2°C] (Apparent: [Apparent/Feels Like, e.g. ~17.1°C - 17.4°C])
- **Humidity**: [Humidity, e.g. 77%]
- **Wind**: [Wind Speed and direction if known, e.g. ~20 - 24 km/h]
- **Daily Peak Temperature**: [Daily Max Temperature, e.g. 20.9°C]
- **Coaching Context**: [Explain how weather and timing choices impacted physiological stress and cardiac drift.]

### 3. Physiological Analysis & Intensity Compliance
- **Intensity Compliance**: [Coaching assessment of effort zones. E.g. "Excellent. Stayed in Zone 1 for recovery."]
- **Pace vs. Heart Rate Efficiency**: [Assess aerobic efficiency. E.g., "Maintaining Zone 1 HR at Zone 2 pace indicates strong aerobic efficiency."]
- **Aerobic Decoupling (Pa:Hr)**: [Decoupling percentage, e.g. 6.16%, and brief analysis of lap-by-lap HR drift vs speed/effort.]

### 4. Biomechanical & Injury Context
- [Biomechanical analysis, e.g. cadence impact on joint loading, step length, and compliance with recovery guidelines from injuries like calf build-up.]

### 5. Long-Term Goal Progress
- **Goal**: [Goal, e.g. Completing the NYC Marathon on November 1st, 2026]
- **Status**: [Status assessment: ON TRACK, AHEAD OF SCHEDULE, or ADJUSTMENTS REQUIRED]
