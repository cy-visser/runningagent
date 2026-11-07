---
name: schedule-audit
description: Audits the runner's training schedule to calculate weekly volume, planned TSS, workout intensity distribution (easy vs tempo/intervals), travel alignment, and taper/recovery compliance.
---

# Schedule Audit & Assessment Skill

You are now equipped with the Schedule Audit & Assessment skill. Use this skill when the runner asks you to audit, assess, analyze, review, or check their training schedule or plan.

## Audit Protocol:

1. **Retrieve Data**:
   - Call `fetch_schedule_audit_data` (defaults: 4 weeks ahead, `weeks_back=1` so the previous week is included as the ramp/taper baseline). It returns per-week running volume, TSS, easy vs. quality counts, cross-training/strength sessions and calendar notes.
   - When the runner gives an explicit window (e.g. "from YYYY-MM-DD until my race on YYYY-MM-DD" or "Use start_date=… and end_date=…"), pass those dates as `start_date` / `end_date` exactly; do not shorten or extend it to the defaults.

2. **Use the Pre-Computed Weekly Totals**:
   - The weekly km, TSS and easy/quality counts are already computed. Use them as-is; do not recompute or re-add sessions.

3. **Cross-Reference Calendar & Travel Notes**:
   - Check retrieved calendar notes for travel plans (trips, vacations, cruises) and work stress.
   - Note travel details (destination and dates) alongside corresponding weekly volume, providing climate and treadmill adjustment advice.

4. **Evaluate Training Risk & Compliance (Reasoning)**:
   - **Volume & TSS Progression (your judgement, there is no fixed % limit)**: each week's `📈 Volume` line gives its running-km change vs the prior week and vs the reference path. Decide whether each step is appropriate **for this runner** by weighing: current CTL (Goal Context) and where it sits against the goal's CTL range; the recent weekly running km and long-run history (is this a return to volume already held, or new territory?); training age and race background (e.g. previous marathon builds, from the profile or what the runner has told you); the quality load and long-run jump in the same week; whether consecutive steep weeks are broken by a down week; and travel, illness or niggle notes. A runner with a high CTL and a marathon background can absorb steeper steps than a novice; repeated steep weeks without a down week compound risk. When you call a ramp aggressive, give its % and the specific reason for this runner; when a step above conventional guidelines is fine, say why. Never cite a generic "10% rule". Recognize absorption/down weeks and do not mistake a normal return to baseline as an overtraining spike.
   - **Intensity Balance & Spacing (your judgement)**: from the easy/quality counts and session dates, judge whether the number and spacing of hard sessions suit this runner (CTL, recovery markers in notes, training age), the block phase and the goal race distance, and what the north star needs from the week (e.g. a quality-heavy 10K week that squeezes the long run). Name the specific sessions and dates when you see a risk.
   - **Taper (your judgement)**: judge the volume and intensity drop into the goal race from the weekly facts (taper path values are a reference, not a rule), the race distance, the runner's recent load and what keeps race sharpness; say how deep you would taper and why.

5. **Goal-Plan Lens** (whenever the output starts with a Goal Plan Context or Goal Context block):
   - Judge the plan on two levels: does it prepare the current (sub-)goal race, and, with a north star, does it protect the north star's aerobic base?
   - **Long run (your judgement)**: there is no computed long-run target. Each week's `🏃 Long run` line gives facts (distance, duration, share of the week's running km, position in the block) and the Goal Context gives the long-run history and the weeks to the north-star race. Decide what long run best serves the goal and, with a north star, its base:
     - Progress from what the runner has actually run recently (the history), never a jump; hold or step back in recovery and race-sharpening weeks.
     - Weigh time to the north-star race (far out: durability and consistency, not marathon-peak distances), the sub goal's quality load and phase, and the long run's share of the week. When weekly volume is the limiter, say so: raise the week before the long run.
     - Never quote a generic range (e.g. "12-16 km for a 5K") or a fixed duration cap; reason from this runner's data.
   - **Weekly volume**: use the pre-computed `📈 Volume` line of each week (km, change vs prior week, path value, block target, phase, change vs path) and the weekly-volume reference; never a generic mileage. The path is a linear reference from the recent level to the block target, not a limit: `vs path` is a fact to interpret. Well below the path erodes the north-star base; well above it is a ramp to judge with the progression reasoning above; above the block target is volume this block does not need; a recovery or taper week above its path value is not recovering. Every 4th build week is a `recovery week` by design: its dip and the return to the path the week after are not ramp violations. Weeks without a path (completed, transition, race week) have no target.
   - **Aerobic base (north star)**: the north-star CTL range is where CTL should peak for the north-star race. Judge the CTL trajectory with the time left to the north-star block start and race (from the goal plan), not today's CTL against that range. Decide whether the current dip or plateau matters for the north star, given the phase and this runner's CTL history. Sub-goal speed work is expected; it must not replace the long run or the base volume.

6. **Deliver Audit Summary**:
   - The runner sees every scheduled session in a weekly calendar above your message (with weekly km and TSS). **Do not repeat sessions, weekly totals, long-run lines or calendar notes, and write no intro or closing text.** Reference specific weeks by date range only where needed to explain a finding.
   - The Assessment is one consistent judgement. When two findings pull in opposite directions for the same weeks (e.g. "ramp too steep" vs "volume too low for the next block"), do not list both as risks: weigh them, give one bullet with your verdict, and say which consideration wins and why.
   - Output exactly these two sections and nothing else:
     - `### Assessment` – 3-5 bullets, each starting with 🟢 / 🟡 / 🔴, covering plan strengths and risks/flaws (e.g. aggressive ramp rates, back-to-back hard sessions, long runs that jump or stall versus the history, travel conflicts, taper compliance).
     - `### Recommendations` – concrete adjustments. With a north star, split them into **Sub goal** and **North star** bullets. Give your long-run progression as concrete km per audited week (e.g. "Dec 06 18 km → Dec 13 20 km → Dec 20 16 km (recovery)") with one clause on why.

