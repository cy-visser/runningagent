---
name: schedule-audit
description: Audits the runner's training schedule to calculate weekly volume, planned TSS, workout intensity distribution (easy vs tempo/intervals), travel alignment, and taper/recovery compliance.
---

# Schedule Audit & Assessment Skill

You are now equipped with the Schedule Audit & Assessment skill. Use this skill when the runner asks you to audit, assess, analyze, review, or check their training schedule or plan.

## Audit Protocol:

1. **Retrieve Data**:
   - Call `fetch_schedule_audit_data` (defaults: 4 weeks ahead, `weeks_back=1` so the previous week is included as the ramp/taper baseline). It returns per-week running volume, TSS, easy vs. quality counts, cross-training/strength sessions and calendar notes.

2. **Use the Pre-Computed Weekly Totals**:
   - The weekly km, TSS and easy/quality counts are already computed. Use them as-is; do not recompute or re-add sessions.

3. **Cross-Reference Calendar & Travel Notes**:
   - Check retrieved calendar notes for travel plans (trips, vacations, cruises) and work stress.
   - Note travel details (destination and dates) alongside corresponding weekly volume, providing climate and treadmill adjustment advice.

4. **Evaluate Training Risk & Compliance (Reasoning)**:
   - **Volume & TSS Progression**: Flag weekly running volume growth of more than 10% over the prior week (and TSS growth of more than 15%). Recognize absorption/down weeks and do not mistake a normal return to baseline as an overtraining spike.
   - **Intensity Balance & Spacing**: Max 1-2 hard/quality workouts per week, spaced with recovery days. Flag 3+ quality sessions or back-to-back hard days as high injury/overtraining risks.
   - **Taper Compliance**: Ensure the week(s) leading to the goal race reduce volume by 40-60% vs. peak weekly mileage.

5. **Goal-Plan Lens** (whenever the output starts with a Goal Plan Context or Goal Context block):
   - Judge the plan on two levels: does it prepare the current (sub-)goal race, and, with a north star, does it protect the north star's aerobic base?
   - **Long run**: use only the pre-computed `🏃 Long run` line of each week (target range, phase and flag). Never substitute a generic range (e.g. "12-16 km for a 5K"). Report `⚠` flags; a `transition` / `race week` week has no long-run target.
   - **Aerobic base (north star)**: flag weekly volume dropping well below recent weeks, or a plan that moves CTL away from the north-star peak CTL reference range, as north-star risks. Sub-goal speed work is expected; it must not replace the long run or the base volume.

6. **Deliver Audit Summary**:
   - The runner sees the weekly breakdown (volume, individual easy vs. quality runs, bike & strength cross-training, long-run targets and calendar notes) as an interactive stacked-bar chart above your message — **do not repeat the week-by-week list or session listings in text**. Reference specific weeks by date range only where needed to explain a finding.
   - Provide an objective evaluation highlighting plan strengths, potential risks/flaws (e.g. back-to-back hard sessions, aggressive ramp rates, long-run `⚠` flags, travel conflicts), and recommended adjustments.
   - With a north star, split the recommended adjustments into **Sub goal** and **North star** bullets.
