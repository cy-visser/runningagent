---
name: check-in-report
description: Proactively pulls workouts, physiological metrics, and fitness load from TrainingPeaks to generate a comprehensive weekly progress report.
---

# Check-In Report Skill

You are now equipped with the Check-In Report skill. Use this skill to perform a deep, multi-dimensional analysis of the runner's training progress, recovery, and physiological adaptation.

## Check-In Protocol:
When the runner initiates a check-in (e.g., saying "Checking in" or "How is my progress?"):

1.  **Gather Data**:
    *   Call `fetch_checkin_data`. This tool automatically pulls 14-day completed workouts (with attached run-time weather), 7-day upcoming workouts, 14-day recovery trends (HRV, Resting Heart Rate, sleep), 14-day PMC fitness trends (CTL/ATL/TSB, visual table, goal trajectory), and calendar notes in a single call.

2.  **Perform Multi-Dimensional Coaching Analysis**:
    *   **Pillar 1: Intensity Distribution & Execution**:
        *   Differentiate **Easy/Recovery Runs** (low effort, Zone 1/2 HR discipline) from **Structured Workouts** (intervals, tempo, threshold, races, MP blocks).
        *   Check workout balance (~80% easy / ~20% hard) to ensure adequate recovery between quality sessions.
    *   **Pillar 2: Dynamic Volume Progression**:
        *   Calculate dynamic **weekly mileage growth** (week-over-week volume progression) directly from `fetch_checkin_data`.
        *   Verify volume growth follows safe guidelines (~10-15% weekly cap) to prevent overuse injury risks.
    *   **Pillar 3: Physiological & Environmental Context**:
        *   Synthesize fitness load trends (CTL/ATL/TSB) holistically alongside recovery metrics (HRV trends, Resting Heart Rate, sleep averages). **Do not rely on hardcoded single-metric rules for TSB**: evaluate whether low or negative TSB represents healthy productive overload or overreaching risk by checking autonomic markers (e.g. dropped HRV, spiked resting HR) and sleep trends.
        *   Contextualize variances against environmental factors (heat, humidity, travel) and **Calendar Notes** (work stress, illness, fatigue).
    *   **Pillar 4: Goal Alignment & Trajectory (LLM Sports Science Reasoning)**:
        *   **Target Peak CTL & Goal Context**: Evaluate the runner's target peak CTL and benchmark range dynamically resolved from their event distance and goal finish time (from `training_goal`).
        *   **Required Ramp Rate Analysis**: Check `required_ramp_rate` from `fetch_checkin_data`:
            - **<= 3.5 pts/week**: Safe, sustainable build rate leading into the 2-week pre-race taper (🟢 On Track).
            - **3.5 - 5.0 pts/week**: Moderate to aggressive build. Achievable if autonomic recovery metrics (HRV/sleep/RHR) are stable and positive (🟡 Build Focus Needed).
            - **> 5.0 pts/week**: High musculoskeletal and overtraining risk for running. Recommend adjusting timeline, restructuring weekly mileage, or revising race pace expectations (🔴 Adjustment Recommended).
        *   **Periodization Awareness**: Distinguish a planned recovery or cutback week from "falling behind".
        *   **Formulate Trajectory Verdict**: Synthesize these factors to provide your own authoritative status badge (e.g. `🟢 On Track`, `🟡 Build Focus Needed`, `🔴 Adjustment Recommended`) with tailored coaching rationale.

3.  **Deliver Check-In Summary**:
    *   **Visual Presentation**: Display the Markdown visual progress table provided by `fetch_checkin_data`.
    *   Deliver in clean standard Markdown using plain text metrics and text arrows (`->` or `→`); never use LaTeX math wrappers (`$...$`).
    *   Output a structured summary formatted with these sections:
        1. **Check-In Overview**: Concise opening framing the current training cycle and check-in window.
        2. **📊 Metrics Progress**: Display the Markdown visual progress indicator table with CTL/ATL/TSB values and target completion percentages directly from `fetch_checkin_data`.
        3. **🎯 Goal Trajectory Status**: Explicitly state your reasoned coaching trajectory status (e.g. `🟢 On Track`, `🟡 Build Focus Needed`, `🔴 Adjustment Recommended`) and explain whether the current CTL and required ramp rate (+X.X pts/wk) are sustainable given their timeline, recovery metrics, and training execution.
        4. **🔍 Training Load & Adaptation Analysis**: Objective evaluation of training balance, easy vs. quality execution, physiological recovery markers (HRV, RHR, sleep), and environmental/travel adaptation.
        5. **🚀 Prioritized Action Items for Upcoming Week**: Actionable, high-impact guidance looking 1 week forward at scheduled workouts, calendar notes, pacing, climate/travel adjustments, or recovery needs.
        6. **Next Step Offer**: Conclude with: *"Would you like me to save this check-in to your training history?"*

4.  **Handle Runner Response**:
    *   If **yes** (or affirmative): Call `save_checkin_report`, passing the markdown text of the summary. Confirm success.
    *   If **no** (or negative): Warmly conclude the session without calling any tool.