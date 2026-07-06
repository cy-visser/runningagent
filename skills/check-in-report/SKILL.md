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
    *   **Holistic Contextualization**: Do not analyze numbers in a vacuum. Evaluate metrics *through the lens* of the runner's calendar notes and environment (e.g., a drop in HRV or a spike in RHR should be reasoned against travel stress, a sudden heatwave, or a massive spike in weekly ATL).
    *   **Consistency & Compliance**: Review the completed vs. planned runs in the summary. Identify any missed sessions or significant deviations, cross-referencing them with **Calendar Notes** to determine the *why* behind the variance.
    *   **Physiological & Training Load Trends**: Synthesize the relationship between training load trends (CTL/ATL/TSB) and physiological recovery metrics (HRV trend, sleep averages, and Resting Heart Rate trends). Look for alignment or divergence (e.g., if CTL is rising but HRV is stable, they are adapting well; if TSB is deeply negative and HRV is crashing, flag under-recovery).
    *   **Long-Term Goal Alignment**: Compare their current fitness (CTL), weekly mileage, and consistency against their ultimate goal and target race date (from their profile). Critically assess if their current trajectory matches the timeline required for their race.
    *   **Actionable Recommendations**: Formulate clear, specific advice based on the data trends rather than generic coaching axioms. 

3.  **Deliver a Structured Progress Report**:
    *   Format the report exactly using the Markdown Template below.
    *   You MUST call the `save_report_to_artifacts` tool to save and render the report in the Artifacts pane (use filename `weekly_checkin_report.md`).
    *   Do NOT print the full report in the chat.
    *   In the chat, provide a warm, encouraging summary of their week, highlight 2-3 key recommendations, and let them know the full report is available for more details.

4.  **Offer to Save the Report**: Immediately after delivering the report, ask the runner: *"Would you like me to save this check-in report to your training history?"* (or similar). Stop and wait for their response.

5.  **Save the Report**:
    *   If they say **yes** (or a yes-like response), call the `save_checkin_report` tool, passing the full markdown text of the report. Acknowledge and confirm when the tool returns success.
    *   If they say **no** (or a no-like response), acknowledge and conclude the session without calling the tool.

## Mandatory Report Template:

# Weekly Check-In Report: [Date Range]

### 1. Overall Training Summary
[A 2-3 sentence high-level coaching summary of the week's training, adaptation, and overall feel.]

### 2. Training Consistency & Compliance
*   **Running**: [Analysis of completed vs planned runs, total mileage, and compliance.]
*   **Strength Training**: [Number of completed strength sessions and their role in your recovery/injury prevention.]

### 3. Physiological Adaptation & Environmental Stress
*   **Sleep**: [Average sleep hours and impact on recovery.]
*   **Resting Heart Rate (RHR)**: [RHR trend (e.g., "58 -> 52 bpm") and latest value, explaining what it means for your cardiovascular adaptation.]
*   **HRV**: [HRV trend and latest value (e.g., "45ms"), explaining your autonomic nervous system state.]
*   **Environmental & Contextual Stress**: [Synthesize weather conditions at run times with any Calendar Notes (e.g., travel to Milan, heatwave planning). Explain how timing choices, climate, or life logistics impacted their cardiovascular load, cardiac drift, and overall recovery.]

### 4. Training Load & Fitness Trends (PMC)
*   **Fitness (CTL)**: [CTL start -> end and what it means for long-term building.]
*   **Fatigue (ATL)**: [ATL start -> end and acute fatigue level.]
*   **Form (TSB)**: [TSB start -> end, current physiological state (e.g., Fresh, Freshness/Race Ready, Over-reaching), and under-recovery risk.]

### 5. Coach's Recommendations & Action Plan
[Provide 2 to 4 highly specific, actionable recommendations for the upcoming week based on your analysis. Focus on the most critical areas needing attention (e.g., training adjustments, recovery focus, hydration/fueling, or injury prevention), tailored entirely to the runner's current state.]

### 6. Long-Term Goal Progress
*   **Goal**: [State their ultimate training goal, e.g., "Finish Amsterdam Marathon in under 4 hours on October 18th, 2026".]
*   **Pace Assessment**: [Clear declaration: "ON TRACK", "AHEAD OF SCHEDULE", or "ADJUSTMENTS REQUIRED", followed by an honest explanation comparing their current fitness (CTL) and mileage build to where they need to be at this stage of the timeline.]
*   **Next Milestone**: [The next major milestone they need to hit (e.g., "Complete your first 14km long run next week" or "Reach a stable CTL of 35 by week 6").]