---
name: schedule-audit
description: Audits the runner's training schedule to calculate weekly volume, planned TSS, workout intensity distribution (easy vs tempo/intervals), travel alignment, and taper/recovery compliance.
---

# Schedule Audit & Assessment Skill

You are now equipped with the Schedule Audit & Assessment skill. Use this skill when the runner asks you to audit, assess, analyze, review, or check their training schedule or plan.

## Audit Protocol:

1. **Retrieve Data**:
   - Call `fetch_schedule_audit_data`. This tool retrieves the upcoming training schedule, pre-calculates weekly running volume & planned TSS, computes easy vs. quality distributions, maps cross-training/strength sessions, and bundles calendar travel notes in one call.

2. **Calculate Weekly Aggregates**:
   - Sum total weekly volume (km) and total planned TSS.
   - Count workout intensity distribution: Easy runs vs. Hard/Quality workouts (intervals, tempo, threshold).

3. **Cross-Reference Calendar & Travel Notes**:
   - Check retrieved calendar notes for travel plans (trips, vacations, cruises) and work stress.
   - Note travel details (destination and dates) alongside corresponding weekly volume, providing climate and treadmill adjustment advice.

4. **Evaluate Training Risk & Compliance (Reasoning)**:
   - **Volume & TSS Progression**: Verify that weekly volume ramp rate remains under 10% per week (and planned TSS ramp under 15% per week). Recognize absorption/down weeks and do not mistake a normal return to baseline as an overtraining spike.
   - **Intensity Balance & Spacing**: Max 1-2 hard/quality workouts per week, spaced with recovery days. Flag 3+ quality sessions or back-to-back hard days as high injury/overtraining risks.
   - **Taper Compliance**: Ensure the week(s) leading to the goal race reduce volume by 40-60% vs. peak weekly mileage.

5. **Deliver Audit Summary**:
   - Present the audit week-by-week using clear headers:
     `* **[Date Range]:** [Volume] km ([Total Runs] runs: [X] easy, [Y] quality [Optional: | [A] bike, [B] strength]) | Planned TSS: [Total TSS] [Optional: (Travel to [Location])]`
   - Provide an objective evaluation highlighting plan strengths, potential risks/flaws (e.g. back-to-back hard sessions, aggressive ramp rates), and recommended adjustments.
