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

3.  **Deliver Lightweight Check-In Summary (Chat Only)**:
    *   **CRITICAL - NO ARTIFACT RULE**: Do NOT call `save_report_to_artifacts` and do NOT generate a full multi-section detailed report.
    *   In your chat message to the runner, output ONLY a concise, encouraging summary formatted with these exact sections:
        1. **Warm Greeting**: Acknowledging the check-in.
        2. **🌟 Key Highlights & Celebration**: 3-4 bullet points explicitly covering: (a) whether they made progress toward their goals/milestones, (b) how they are handling the workouts based on physiological data (e.g., RHR, HRV, sleep, cardiac drift), and (c) factoring in environmental/weather conditions (e.g., early morning timing, heat, humidity).
        3. **🚀 Top 3 Action Items for this Week**: Exactly 3 prioritized, highly actionable bullet points telling the runner what to focus on this week—especially focusing on **pacing** and relating all adjustments or targets directly to achieving their long-term goal (e.g., NYC Marathon), alongside climate/travel adjustments, hydration, or injury prevention.
        4. **Next Step Offer**: Conclude by asking: *"Would you like me to create a detailed training report for this week (or any specific period), or save this check-in to your training history?"* Stop and wait for their response.

4.  **Handle Runner Response**:
    *   If they ask to create a detailed report for this week or any period, load the `detailed-report` skill using `load_skill` and follow its instructions.
    *   If they say **yes** to saving to training history (or a yes-like response), call the `save_checkin_report` tool, passing the markdown text of the summary you just delivered. Acknowledge and confirm when the tool returns success.
    *   If they say **no** (or a no-like response), acknowledge and conclude the session without calling any tool.