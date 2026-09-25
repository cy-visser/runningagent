---
name: check-in-report
description: Proactively pulls workouts, physiological metrics, and fitness load from TrainingPeaks to generate a comprehensive weekly progress report.
---

# Check-In Report Skill

You are now equipped with the Check-In Report skill. Use this skill to perform a deep, multi-dimensional analysis of the runner's training progress, recovery, and physiological adaptation.

## Check-In Protocol:
When the runner initiates a check-in (e.g., saying "Checking in" or "How is my progress?"):

1.  **Gather Data**:
    *   Call `fetch_checkin_data`. This tool automatically pulls 14-day completed workouts (with attached run-time weather), 7-day upcoming workouts, 14-day recovery trends (HRV, Resting Heart Rate, sleep), 14-day PMC fitness trends (CTL table, ATL/TSB load context, goal trajectory), a **projected finish time for the runner's goal race** (distance and goal time from `training_goal`), and calendar notes in a single call.

2.  **Perform Multi-Dimensional Coaching Analysis**:
    *   **Pillar 1: Intensity Distribution & Execution**:
        *   Differentiate **Easy/Recovery Runs** (low effort, Zone 1/2 HR discipline) from **Structured Workouts** (intervals, tempo, threshold, races, MP blocks).
        *   Check workout balance (~80% easy / ~20% hard) to ensure adequate recovery between quality sessions.
    *   **Pillar 2: Dynamic Volume Progression**:
        *   Use the pre-computed **Weekly Totals** section (km, TSS, easy/quality counts per week); do not re-add workouts yourself.
        *   Flag weekly running volume growth of more than 10% over the prior week as an overuse-injury risk (recognise planned cutback/return-to-baseline weeks).
    *   **Pillar 3: Physiological & Environmental Context**:
        *   Synthesize fitness load trends holistically alongside recovery metrics (HRV trends, Resting Heart Rate, sleep averages). ATL and TSB are provided on the `Load context (analysis only, not displayed)` line: use them for reasoning but do not render them as table rows. **Do not rely on hardcoded single-metric rules for TSB**: evaluate whether low or negative TSB represents healthy productive overload or overreaching risk by checking autonomic markers (e.g. dropped HRV, spiked resting HR) and sleep trends.
        *   Contextualize variances against environmental factors (heat, humidity, travel) and **Calendar Notes** (work stress, illness, fatigue).
    *   **Pillar 4: Goal Alignment & Trajectory (LLM Sports Science Reasoning)**:
        *   **Target Peak CTL & Goal Context**: Evaluate the runner's target peak CTL and benchmark range dynamically resolved from their event distance and goal finish time (from `training_goal`).
        *   **Required Ramp Rate Analysis**: The CTL row shows `Req. Ramp` with a pre-computed tier badge (thresholds are defined in code; quote the badge, do not re-derive it):
            - 🟢 safe: sustainable build into the pre-race taper (🟢 On Track).
            - 🟡 aggressive: achievable only if HRV/sleep/RHR are stable and positive (🟡 Build Focus Needed).
            - 🔴 high risk: recommend adjusting the timeline, restructuring weekly mileage, or revising the goal (🔴 Adjustment Recommended).
        *   **Projected Goal-Race Time (Race Readiness)**: The `Projected {goal}` row shows **Today** (race run tomorrow at current fitness) → **Race day** (projected CTL after a safe build + taper), plus goal, gap, range, confidence and a health readiness flag. It is computed deterministically from the **Projection drivers** table: threshold laps vs the TP threshold setting, goal-pace segments (judged by %LTHR and lap Pa:Hr decoupling), an HR→pace efficiency fit, durability (longest run + long-run Pa:Hr), load (CTL → race day) and health (HRV/RHR/sleep 5d vs 28d). Easy/Zone 2 runs are never treated as race efforts. **Quote the times, gap and confidence exactly as provided; never invent, recompute, or alter them.**
            - Explain the **limiting drivers**: which signal is slowest, and why (e.g. MP block ran at 90% LTHR, long-run decoupling > 5%, durability `weak`, no threshold laps confirming the TP setting). Tie `Goal-pace work` and `Threshold anchor` evidence to specific sessions by date.
            - Use the gap between **Today** and **Race day** to discuss what the remaining build must deliver, and read it alongside TSB: a deeply negative TSB means today's number understates fitness; state whether the race-day gap to goal is realistically closable.
            - **Health flag**: 🟡 "training-induced, expected to clear in taper" is normal during heavy load, so do not alarm the runner, but monitor it. 🔴 outside race week means the poor trend is not explained by load (illness/stress?): make it an action item. 🔴 in race week already includes a race-day time penalty: prioritise rest, sleep and a conservative pacing plan.
            - If confidence is **Low** or `⚠️ stale evidence` is shown (evidence predates the current block or is > 3 weeks old, or signals disagree), recommend specific test sessions for the goal distance, e.g. 5K/10K: a 3 km or 5 km time trial / parkrun, or 2 × 15' @ threshold; HM: 3 × 3 km @ HM pace; Marathon: 2 × 20' @ threshold and a long run with 10–14 km @ goal MP.
            - If the row says `Insufficient recent run data` or `No race distance in goal`, say so briefly and suggest how to get a baseline.
        *   **Periodization Awareness**: Distinguish a planned recovery or cutback week from "falling behind".
        *   **Formulate Trajectory Verdict**: Synthesize these factors to provide your own authoritative status badge (e.g. `🟢 On Track`, `🟡 Build Focus Needed`, `🔴 Adjustment Recommended`) with tailored coaching rationale.

3.  **Deliver Check-In Summary**:
    *   Deliver in clean standard Markdown, following the coach's standard plain-text formatting rules (plain metrics, text arrows `->` or `→`, never LaTeX).
    *   Output a structured summary formatted with these sections:
        1. **Check-In Overview**: Concise opening framing the current training cycle and check-in window.
        2. **📊 Metrics Progress**: Display the Markdown visual progress table (CTL fitness with target completion percentage, and the Projected goal-race time today → race day with goal gap, confidence and readiness) and the **Projection drivers** table directly from `fetch_checkin_data`.
        3. **🎯 Goal Trajectory Status**: Explicitly state your reasoned coaching trajectory status (e.g. `🟢 On Track`, `🟡 Build Focus Needed`, `🔴 Adjustment Recommended`) and explain whether the current CTL, required ramp rate (+X.X pts/wk), and projected race time vs goal are sustainable/achievable given their timeline, recovery metrics, and training execution.
        4. **🔍 Training Load & Adaptation Analysis**: Objective evaluation of training balance, easy vs. quality execution, physiological recovery markers (HRV, RHR, sleep), and environmental/travel adaptation.
        5. **🚀 Prioritized Action Items for Upcoming Week**: Actionable, high-impact guidance looking 1 week forward at scheduled workouts, calendar notes, pacing, climate/travel adjustments, or recovery needs.
        6. **Next Step Offer**: Conclude with: *"Would you like me to save this check-in to your training history?"*

4.  **Handle Runner Response**:
    *   If **yes** (or affirmative): Call `save_checkin_report`, passing the markdown text of the summary. Confirm success.
    *   If **no** (or negative): Warmly conclude the session without calling any tool.