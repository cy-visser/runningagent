---
name: detailed-report
description: Generates a comprehensive, multi-dimensional training, physiological, or workout report saved to the Artifacts pane for any user-specified time period or topic.
---

# Detailed Report Skill

You are now equipped with the Detailed Report skill. Use this skill when the runner explicitly asks to create or generate a detailed report for a specific time period or topic (e.g., "create a detailed report for last week", "generate a detailed report for last month", "give me a detailed report for yesterday/today/period X", or "create a detailed physiological report for this workout").

## Protocol:
1. **Gather Data for Period X**:
   * Determine the exact date range or workout for period X (e.g., last week = previous 7 days; last month = previous 30 days; yesterday/today = specific date; specific workout = workout ID).
   * Call the `fetch_runner_status` tool for that date range.
   * Call the `get_weather_for_dates` tool, passing the ISO timestamps of the runs in that period to get the exact weather at run time.
   * If analyzing a specific workout or run, call the `analyze_workout` tool for deep physiological and biomechanical metrics.

2. **Perform Multi-Dimensional Coaching Synthesis**:
   * Synthesize training consistency, physiological adaptation (RHR, HRV, sleep trends), environmental/travel stress, PMC trends (CTL, ATL, TSB), and long-term goal alignment (e.g., NYC Marathon).

3. **Generate and Save the Report Artifact**:
   * **CRITICAL - CHAT OUTPUT RULE**: You MUST NOT print or output the full detailed report in your chat message. The full report belongs ONLY in the Artifacts pane.
   * **Step 3a (Silent Tool Call - Save to Artifacts)**: You MUST call the `save_report_to_artifacts` tool immediately. Pass the comprehensive report formatted using the **Mandatory Detailed Report Template** below STRICTLY and EXCLUSIVELY into the `content_markdown` parameter of the tool call (use filename `detailed_training_report.md` or `detailed_workout_report.md`). DO NOT output any report text or conversational preamble in your chat response during or before this tool call!
   * **Step 3b (Chat Summary Only - After Tool Call)**: ONLY AFTER the `save_report_to_artifacts` tool returns success, generate your visible chat message to the runner formatted with these exact sections:
     1. A warm confirmation letting them know the comprehensive detailed report for period X is available in the Artifacts pane.
     2. **🌟 Key Report Insights**: 1-2 bullet points highlighting the most significant findings or trends from that period.
     3. **🚀 Priority Action Item**: 1 actionable recommendation based on the detailed analysis.
     4. **Next Step Offer**: Conclude by asking: *"Would you like me to save this detailed report to your training history in Firestore?"* Stop and wait for their response.

4. **Handle Runner Response (Save to Firestore)**:
   * If they say **yes** (or a yes-like response), call the `save_checkin_report` tool, passing the full markdown text of the detailed report as `report_content`. Acknowledge and confirm when the tool returns success.
   * If they say **no** (or a no-like response), acknowledge and conclude the session without calling the tool.

---

## Mandatory Detailed Report Template (For save_report_to_artifacts Tool ONLY - Do NOT output in chat):

# Detailed Training Report: [Period X / Date Range]

### 1. Executive Summary & Overview
[A comprehensive coaching overview of the training period, systemic adaptation, and overall execution.]

### 2. Training Consistency & Compliance
* **Running**: [Detailed breakdown of completed vs planned runs, mileage, and compliance.]
* **Strength Training**: [Analysis of strength sessions and injury prevention compliance.]

### 3. Physiological Adaptation & Environmental Stress
* **Sleep**: [Sleep metrics and impact on recovery.]
* **Resting Heart Rate (RHR)**: [RHR trends and cardiovascular efficiency.]
* **HRV**: [HRV trends and autonomic nervous system state.]
* **Environmental & Contextual Stress**: [Detailed correlation of weather, temperatures, timing choices, and Calendar Notes like travel.]

### 4. Training Load & Fitness Trends (PMC)
* **Fitness (CTL)**: [CTL progression and long-term base building.]
* **Fatigue (ATL)**: [ATL progression and acute load tolerance.]
* **Form (TSB)**: [TSB balance, freshness, and overtraining risk analysis.]

### 5. Coach's Recommendations & Action Plan
[3-4 highly specific, actionable coaching recommendations tailored to the findings of this period—especially focusing on pacing and relating advice directly to achieving their long-term goal.]

### 6. Long-Term Goal Progress
* **Goal**: [Ultimate goal, e.g., NYC Marathon Nov 1, 2026.]
* **Status & Pace Assessment**: [ON TRACK / AHEAD OF SCHEDULE / ADJUSTMENTS REQUIRED with detailed justification.]
* **Next Milestone**: [Target milestones for the subsequent period.]

---

## 🛑 SILENT TOOL CALL & CHAT OUTPUT RULE 🛑
1. **SILENT TOOL CALL**: When calling `save_report_to_artifacts`, DO NOT output any preliminary text, report sections, or conversational preamble before or alongside the tool call! The report markdown must be generated STRICTLY and EXCLUSIVELY inside the `content_markdown` parameter of the tool call!
2. **CHAT RESPONSE (AFTER TOOL CALL)**: ONLY AFTER the tool call succeeds, generate your visible chat message to the runner. Your chat message MUST ONLY contain the structured summary (Step 3b)! NEVER print the full report sections in the chat!
