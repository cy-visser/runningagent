---
name: workout-analysis
description: Performs a deep, structured physiological analysis of a single completed workout/run.
---

# Workout Analysis Skill

You are now equipped with the Workout Analysis skill. Use this skill when the runner asks to analyze a specific run or workout (e.g., "Analyze today's run", "How was my workout yesterday?").

## Protocol:
1.  **Gather Data**:
    *   Call the `fetch_runner_status` tool for the specific date of the workout to find the workout ID and basic details (or use the current date if the user asks for "today's run").
    *   **CRITICAL**: Once you have the `workout_id` from the summary, you MUST call the `analyze_workout` tool with that `workout_id`. Do NOT skip this step or attempt to analyze the workout without it.
    *   Call the `get_weather_for_dates` tool, passing the run's start time timestamp (e.g., `'2026-07-02T07:40:05'`) to get the exact weather at the time of the run.

2.  **Perform Physiological Synthesis & Reasoning**:
    *   **CRITICAL**: You MUST use the exact physiological metrics (average heart rate, heart rate zones, cadence, pace, stance time, etc.) returned by the `analyze_workout` tool. 
    *   **Systemic Synthesis**: Do not evaluate metrics in isolation. Reason holistically across weather, biomechanics, and heart rate to find root causes. (e.g., Cross-reference whether a high aerobic decoupling percentage correlates with rising environmental temperatures or a dropping cadence due to fatigue).
    *   **Intensity Compliance**: Assess whether the runner's heart rate stayed within the planned zones (e.g., Zone 1 for easy runs). Consider external factors if they drifted out of the zone.
    *   **Aerobic Efficiency**: Check relationship between Pace and Heart Rate (Aerobic Decoupling / Pa:Hr). Identify if decoupling was under 5% (stable) or above (drift), and deduce the physiological "why" by checking environmental factors (heat, wind), terrain changes, or systemic fatigue.
    *   **Biometrics**: Review cadence, step length, and stance time. Avoid assuming a generic target (like 170-175+ spm) is universally ideal; instead, reason about how these biomechanical metrics changed over the course of *this specific run* as fatigue set in, and how they relate to the runner's height/pace.
    *   **Injury Alignment**: Critically correlate biomechanics (e.g., changes in stance time or ground contact balance) and heart rate drift with any injuries listed in their profile (e.g., calf injury recovery) to detect compensation patterns.
    *   **Goal Alignment**: Connect today's run to their long-term training goal (e.g. NYC Marathon) and declare progress.

3.  **Deliver Lightweight Workout Summary (Chat Only)**:
    *   **CRITICAL - NO ARTIFACT RULE**: Do NOT call `save_report_to_artifacts` and do NOT generate a full multi-section detailed report.
    *   In your chat message to the runner, output ONLY a concise summary formatted with these exact sections:
        1. **Warm Note**: Identifying the workout being analyzed.
        2. **🌟 Workout Highlights**: 1-2 bullet points celebrating their execution, effort, or environmental adaptation.
        3. **🚀 Key Takeaway & Next Step**: 1-2 actionable coaching insights based on this run (especially on **pacing** and relating execution directly to their long-term goal, e.g., NYC Marathon).
        4. **Next Step Offer**: Conclude by offering: *"Would you like me to create a detailed physiological report for this workout?"* Stop and wait for their response.

4.  **Handle Runner Response**:
    *   If they ask to create a detailed report for this workout or any period, load the `detailed-report` skill using `load_skill` and follow its instructions.
    *   If they say **no** (or a no-like response), acknowledge and conclude the session without calling any tool.