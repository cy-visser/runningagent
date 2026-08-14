---
name: schedule-audit
description: Audits the runner's training schedule to calculate weekly volume, planned TSS, workout intensity distribution (easy vs tempo/intervals), travel alignment, and taper/recovery compliance.
---

# Schedule Audit & Assessment Skill

You are now equipped with the Schedule Audit & Assessment skill. Use this skill when the runner asks you to audit, assess, analyze, review, or check their training schedule or plan.

## Audit Protocol:

1. **Retrieve Data**:
   - Call `fetch_schedule_audit_data`. This tool retrieves the upcoming training schedule, pre-calculates weekly volume & planned TSS, computes easy vs. hard intensity distributions, maps calendar travel notes, and flags risk factors in one call.

2. **Calculate Weekly Aggregates**:
   - Sum total weekly volume (km) and total planned TSS.
   - Count workout intensity distribution: Easy runs vs. Hard/Quality workouts (intervals, tempo, threshold).

3. **Cross-Reference Calendar & Travel Notes**:
   - Check retrieved calendar notes for travel plans (trips, vacations, cruises) and work stress.
   - Note travel details (destination and dates) alongside corresponding weekly volume, providing climate and treadmill adjustment advice.

4. **Evaluate Training Risk Compliance**:
   - **Intensity Balance**: Max 1-2 hard workouts per week. Flag 3+ hard runs as high overtraining/injury risks.
   - **Taper Compliance**: Ensure week leading to race reduces volume by 40-60% vs. peak weekly mileage.
   - **Post-Race Recovery**: Flag high intensity or long runs (>15km) in 7 days post-race as severe injury risks.

5. **Deliver Audit Summary**:
   - Present the audit week-by-week using clear headers:
     `* **[Date Range]:** [Volume] km ([Total Runs] runs: [X] easy, [Y] quality) | TSS: [Total TSS] [Optional: (Travel to [Location])]`
   - Outline plan strengths first, followed by critical warnings and specific recommended adjustments.
