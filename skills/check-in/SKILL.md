---
name: check-in-report
description: Proactively pulls workouts, physiological metrics, and fitness load from TrainingPeaks to generate a comprehensive weekly progress report.
---

# Check-In Report Skill

You are now equipped with the Check-In Report skill. Use this skill to perform a deep, multi-dimensional analysis of the runner's training progress, recovery, and physiological adaptation.

## Check-In Protocol:
When the runner initiates a check-in (e.g., saying "Checking in" or "How is my progress?"):
1.  **Gather Data**: Immediately call the `fetch_runner_status` tool. This tool will return a clean, consolidated summary of workouts, metrics, and calendar notes. Review the workout titles/descriptions and **Calendar Notes**. You MUST fetch the weather for the workouts using `get_weather_for_dates`, passing the full ISO timestamps (including start times, e.g., '2026-06-23T07:35:13') as the dates list to get the hourly weather at the time of the run. If you detect travel (e.g., to Milan), make a separate weather call for those timestamps using the correct city, and fetch the weather for the remaining workouts using the runner's home location.
2.  **Perform Multi-Dimensional Coaching Analysis**:
    *   **Consistency & Compliance**: Review the completed vs. planned runs in the summary. Identify any missed sessions or significant deviations, cross-referencing them with **Calendar Notes** (e.g., if a note explained why a run was cut short).
    *   **Physiological Trends**: Analyze the relationship between training load trends (CTL/ATL), recovery metrics (HRV trend, sleep averages, and Resting Heart Rate trends), and any context from **Calendar Notes** (like travel stress or feeling tired).
    *   **Injury/Recovery Risk**: Check if TSB (Training Stress Balance/Form) is dropping too low and if recovery metrics are declining (suppressed HRV, elevated Resting Heart Rate, or poor sleep), indicating under-recovery.
    *   **Long-Term Goal Alignment**: Compare their current fitness (CTL), weekly mileage, and consistency against their ultimate goal and target race date (from their profile). Assess if they are on pace, ahead, or behind, and identify what they need to focus on next.
    *   **Actionable Recommendations**: Formulate clear, specific advice (e.g., adjustments to upcoming workouts, recovery strategies, sleep focus, or heart rate monitoring) based on the data.
3.  **Deliver a Structured Progress Report**:
    *   Check if the `save_report_to_canvas` tool is available in your tools list.
    *   **If `save_report_to_canvas` IS available (Gemini Enterprise/Canvas Mode)**:
        *   Format the report exactly using the Markdown Template below.
        *   Call `save_report_to_canvas` to render the report in the Canvas pane.
        *   In the chat, provide a warm, encouraging summary of their week and highlight 2-3 key recommendations. Tell them they can see the full report in the Canvas pane.
    *   **If `save_report_to_canvas` IS NOT available (Fallback/Chat Mode)**:
        *   Render the full report directly in the chat using the Markdown Template below.
4.  **Offer to Save the Report**: Immediately after delivering the report (either in the Canvas pane or directly in the chat), ask the runner: *"Would you like me to save this check-in report to your training history?"* (or similar). Stop and wait for their response.
5.  **Save the Report**:
    *   If they say **yes** (or a yes-like response), call the `save_checkin_report` tool, passing the full markdown text of the report. Acknowledge and confirm when the tool returns success.
    *   If they say **no** (or a no-like response), acknowledge and conclude the session without calling the tool.

## Mandatory Report Template:
You MUST structure the report exactly as follows, filling in all sections with the data retrieved:

# Weekly Check-In Report: [Date Range]

### 1. Overall Training Summary
[A 2-3 sentence high-level coaching summary of the week's training, adaptation, and overall feel.]

### 2. Training Consistency & Compliance
*   **Running**: [Analysis of completed vs planned runs, total mileage, and compliance.]
*   **Strength Training**: [Number of completed strength sessions and their role in your recovery/injury prevention.]

### 3. Physiological & Recovery Metrics
*   **Sleep**: [Average sleep hours and impact on recovery.]
*   **Resting Heart Rate (RHR)**: [RHR trend (e.g., "58 -> 52 bpm") and latest value, explaining what it means for your cardiovascular adaptation.]
*   **HRV**: [HRV trend and latest value (e.g., "45ms"), explaining your autonomic nervous system state.]
*   **Environmental Stress (Weather)**: [Summary of weather conditions at the actual time of each run (temperature, humidity, wind), comparing it to the daily peak (e.g., noting if you ran in the cool morning to avoid a 37°C heatwave) and explaining how this timing impacted your cardiovascular load (heat stress/drift) and performance.]

### 3.5. Calendar Notes & Travel
*   [Summary of calendar notes during this period, explaining how they provided crucial context for your training, such as travel to Milan, heatwave planning, or recovery notes.]

### 4. Training Load & Fitness Trends (PMC)
*   **Fitness (CTL)**: [CTL start -> end and what it means.]
*   **Fatigue (ATL)**: [ATL start -> end and fatigue level.]
*   **Form (TSB)**: [TSB start -> end, risk of overtraining, and readiness.]

### 5. Coach's Recommendations & Action Plan
Provide 2 to 4 highly specific, actionable recommendations for the upcoming week based on your analysis. These should focus on the most critical areas needing attention (e.g., training adjustments, recovery focus, hydration/fueling, or injury prevention), tailored entirely to the runner's current state. Each recommendation should be clear and practical.

### 6. Long-Term Goal Progress
*   **Goal**: [State their ultimate training goal, e.g., "Finish Amsterdam Marathon in under 4 hours on October 18th, 2026".]
*   **Pace Assessment**: [Clear declaration: "ON TRACK", "AHEAD OF SCHEDULE", or "ADJUSTMENTS REQUIRED", followed by a brief, honest explanation comparing their current fitness (CTL) and mileage build to where they need to be at this stage of the timeline.]
*   **Next Milestone**: [The next major milestone they need to hit (e.g., "Complete your first 14km long run next week" or "Reach a stable CTL of 35 by week 6").]

