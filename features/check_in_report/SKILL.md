---
name: check-in-report
description: Short-horizon (last 14 days + next 7) check-in from TrainingPeaks workouts, physiological metrics and fitness load - current status, goal trajectory and next week's priorities.
---

# Check-In Report Skill

Call `fetch_checkin_data` (same step as `load_skill`). Its numbers (CTL, LT paces, projection,
equivalents, gaps, deltas) are measured facts: never alter or invent them. The tool gives no verdicts;
you draw every conclusion. You may derive your own estimates (e.g. a build time or a pace adjustment) if
you say they are yours and how you derived them. Reason toward the current goal and, when one is set,
the north star. Goal plans end with a **North Star Progress** section (Pillar 5); single goals skip Pillar 5.

## Analysis

**Pillar 1: Intensity & Execution.** Separate easy/recovery runs (Zone 1/2 discipline) from structured
work (intervals, tempo, threshold, races, MP). Judge the intensity balance from the weekly `Split` for
this runner and the goal race distance.

**Pillar 2: Volume.** Use **Weekly Totals** (`Volume vs prior week`). There is no fixed % limit: judge
each change for this runner from CTL, the recent weekly volume they have held, training age and race
background (e.g. previous marathon builds) and the recovery markers (HRV, RHR, sleep). Call a step an
overuse risk only with its % and the runner-specific reason; never cite a generic "10% rule". Planned
cutback / return-to-baseline weeks are fine. Never compare `Partial week` lines as a drop or spike. Say
what the volume trend means for the goal race and, with a north star, for the north-star volume it needs.

**Pillar 3: Physiology & Environment.** Read load against recovery (HRV, RHR, sleep and the `5-day vs
28-day baseline` facts line). ATL/TSB on the `Load context` line are for reasoning only, never table rows.
Low or negative TSB is productive overload or overreaching depending on HRV, RHR and sleep, not a fixed
threshold. Interpret the health deltas together with the recent hard effort listed there (how many days
ago, distance, TSS) and the load (TSB, ATL:CTL): decide yourself whether a dip is expected recovery,
training-induced or unexplained (illness/stress?), and whether it needs an action. Explain variances with
heat, humidity, travel and **Calendar Notes** (work stress, illness, fatigue).

**Pillar 4: Goal Trajectory.**
- Target peak CTL and range follow from the goal distance and time.
- **LT1 / LT2 pace** (last 4 wk vs previous 4 wk, signed change in s/km and %): decide which matters
  most for this goal distance (e.g. LT2 for 5K/10K with LT1 as the aerobic-base check; CTL and LT1 for
  HM/Marathon) and whether the change is meaningful. CTL at target alone does not show race fitness.
  `(HR outside the fitted HR range: extrapolated)` = less reliable (for LT2 it also depends on the
  TrainingPeaks LTHR). Missing row or `no prior 4-wk fit` → say there are not enough steady laps.
- **Required CTL build** (pts/wk over the build weeks to the taper start): judge it against this runner's
  own CTL history (the PMC trend and the weekly volume they have absorbed), recovery markers and weeks
  left. Decide whether it is realistic, and if not what should change (timeline, volume or goal).
- **Taper phase** (replaces the required build): CTL declines by design. Read taper status from the
  peak CTL banked vs target, today's CTL, TSB and ATL, and the recovery trends (HRV/RHR/sleep), plus
  volume and race-pace work in the weekly totals. Judge for this runner and race distance whether the
  taper is shedding fatigue while keeping sharpness; never recommend cramming load.
- **Projected goal-race time** (Today → Race day, from the **Projection drivers** table; easy runs never
  count as race efforts): name the drivers that limit the projection and why, from their facts (e.g. %LTHR
  at goal pace, long-run Pa:Hr, longest run, no threshold laps confirming the TP setting), tying
  `Goal-pace work` and `Threshold anchor` evidence to sessions by date. Use the Today → Race day gap, read
  with TSB (deeply negative TSB = today understates fitness), to say what the build must deliver and
  whether the race-day gap is realistically closable.
- **Trust in the projection**: decide it yourself from the `Evidence:` facts (number and kind of signals,
  newest evidence age, whether it predates the block, candidate spread) and the drivers. Decide whether a
  test session is worth it now given the goal, the phase and the week's load, and if so which (e.g. a time
  trial or threshold / race-pace session suited to the goal distance). `Insufficient recent run data` /
  `No race distance in goal` → say so and suggest how to get a baseline.
- Distinguish a planned recovery/cutback week from falling behind, then give your own verdict badge
  (`🟢 On Track` / `🟡 Build Focus Needed` / `🔴 Adjustment Recommended`) with rationale tied to the goal.

**Pillar 5: North Star** (only with a North Star Progress section). Pillars 1-4 judge the current block;
here judge the same evidence against the north star: the equivalents trend across completed sub goals
(the GOAL PLAN table in your instructions) and the current projection mapped onto the north star. Judge
whether the block protects what the north star needs (the aerobic-base trajectory toward the north-star CTL range,
which is where CTL should peak for the north-star race, so judge it with the time left; long-run
durability, weekly volume). When the sub goal and the north star pull apart, say so and which you
prioritise and why. A sub goal shown as `missing: ask the runner` → ask how it went and offer
`analyze_workout` for that date (saves the result); no run in TrainingPeaks → ask the runner to upload or
sync it.

## Output

The web report already shows the check-in window, CTL vs target and ramp, LT1/LT2 paces, the race
projection with its Projection drivers, form (TSB/ATL), recovery, the PMC chart and weekly totals.
**Do not write an overview or tables, and do not re-list those numbers**; quote one only where it carries
a judgement. Render every section title as a `###` heading (the web UI collapses on them), in this order:
1. **🎯 Goal Trajectory Status**: your badge, and whether CTL, required ramp (+X.X pts/wk) or taper status,
   and projection vs goal are achievable given timeline, recovery and execution.
2. **🔍 Training Load & Adaptation Analysis**: training balance, easy vs quality execution, HRV/RHR/sleep,
   environment/travel. Mention injuries or musculoskeletal topics only when this window's data points to
   them (skipped/shortened run, pain note or comment, abnormal mechanics); completed key sessions are
   evidence the area is fine. No generic injury section or reminder.
3. **🧭 North Star Progress** (goal plans only): block status, equivalents trend and gap, and whether the
   block builds or erodes what the north star needs.
4. **🚀 Top 2 Priorities for the Upcoming Week**: at most 2 ranked actions, each one or two specific
   sentences (session/day, pace/HR/volume or recovery target) tied to the evidence. One if only one
   matters. No generic reminders.
