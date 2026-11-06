---
name: check-in-report
description: Short-horizon (last 14 days + next 7) check-in from TrainingPeaks workouts, physiological metrics and fitness load - current status, goal trajectory and next week's priorities.
---

# Check-In Report Skill

Call `fetch_checkin_data` (same step as `load_skill`). Every number, badge, verdict, projection,
equivalent and gap in its output is pre-computed: quote it exactly; never re-add, recompute or
re-derive it. Goal plans end with a **North Star Progress** section (Pillar 5); single goals skip Pillar 5.

## Analysis

**Pillar 1: Intensity & Execution.** Separate easy/recovery runs (Zone 1/2 discipline) from structured
work (intervals, tempo, threshold, races, MP). Judge the ~80/20 balance from the weekly `Split`.

**Pillar 2: Volume.** Use **Weekly Totals** (`Volume vs prior week`). Judge a `⚠️ > 10%` growth flag
(overuse risk) in context: planned cutback / return-to-baseline weeks are fine. Never compare
`Partial week` lines as a drop or spike.

**Pillar 3: Physiology & Environment.** Read load against recovery (HRV, RHR, sleep, `5-day vs 28-day
baseline`). ATL/TSB on the `Load context` line are for reasoning only, never table rows. Low or negative
TSB is productive overload or overreaching depending on HRV, RHR and sleep, not a fixed threshold.
Explain variances with heat, humidity, travel and **Calendar Notes** (work stress, illness, fatigue).

**Pillar 4: Goal Trajectory.**
- Target peak CTL and range follow from the goal distance and time.
- **LT1 / LT2 pace** (last 4 wk vs previous 4 wk): 5K/10K → judge progress mainly on the LT2 trend,
  LT1 as the aerobic-base check; CTL at target is only a floor, never "on track" from CTL % alone.
  HM/Marathon → CTL is primary, LT1/LT2 support it. `⚠️ extrapolated` = indicative only (for LT2: depends
  on the TrainingPeaks LTHR). Missing row or `no prior 4-wk fit` → say there are not enough steady laps.
- **`Req. Ramp` badge** (build ends where the taper starts): 🟢 safe → 🟢 On Track; 🟡 aggressive →
  🟡 Build Focus Needed, achievable only if HRV/sleep/RHR are stable; 🔴 high risk → 🔴 Adjustment
  Recommended (adjust timeline, weekly mileage or goal).
- **`🏁 Taper phase`** (replaces `Req. Ramp`): a gradual CTL decline is expected, never lost fitness; do
  not recommend raising CTL or cite a ramp. Judge fitness on the **peak CTL banked** (the projection is
  anchored to it and only moves on new race-pace evidence or the health flag). Judge execution on TSB
  rising toward the +5 to +15 race-day target, volume ~40-60% below peak, short race-pace work kept and
  HRV/RHR/sleep recovering. Banked peak in range → 🟢 On Track; below → adjust goal pace / race strategy,
  never cram load.
- **Projected goal-race time** (Today → Race day, from the **Projection drivers** table; easy runs never
  count as race efforts): name the limiting drivers and why (e.g. MP block at 90% LTHR, long-run
  decoupling > 5%, durability `weak`, no threshold laps confirming the TP setting), tying `Goal-pace work`
  and `Threshold anchor` evidence to sessions by date. Use the Today → Race day gap, read with TSB
  (deeply negative TSB = today understates fitness), to say what the build must deliver and whether the
  race-day gap is realistically closable.
- **Health flag**: 🟡 training-induced → normal under load, monitor, do not alarm. 🟡 recovery after
  '<race or session>' → expected dip, not illness/stress; easy running until the window ends. 🔴 outside
  race week → not explained by load or a race (illness/stress?): make it an action item. 🔴 in race week
  (race-day penalty included) → prioritise rest, sleep and conservative pacing.
- Confidence **Low** or `⚠️ stale evidence` → prescribe a test: 5K/10K a 3 or 5 km time trial / parkrun or
  2 × 15' @ threshold; HM 3 × 3 km @ HM pace; Marathon 2 × 20' @ threshold and a long run with 10-14 km
  @ goal MP. `Insufficient recent run data` / `No race distance in goal` → say so and suggest how to get
  a baseline.
- Distinguish a planned recovery/cutback week from falling behind, then give your own verdict badge
  (`🟢 On Track` / `🟡 Build Focus Needed` / `🔴 Adjustment Recommended`) with rationale.

**Pillar 5: North Star** (only with a North Star Progress section). Pillars 1-4 judge the current block;
here judge the same evidence against the north star: the equivalents trend across completed sub goals
and the current projection mapped onto the north star. Check that the block protects what the north star
needs (aerobic base vs the north-star CTL range, long runs kept in short-distance blocks). A sub goal shown
as `missing: ask the runner` → ask how it went and offer `analyze_workout` for that date (saves the
result); no run in TrainingPeaks → ask the runner to upload or sync it.

## Output

Render every section title as a `###` heading (the web UI collapses on them), in this order:
1. **Check-In Overview**: the current training cycle and check-in window.
2. **📊 Metrics Progress**: only the line `[[CHECKIN_METRICS]]`, once, on its own line. It is replaced
   with the CTL / LT1 / LT2 / projection and Projection drivers tables; never re-type them.
3. **🎯 Goal Trajectory Status**: your badge, and whether CTL, required ramp (+X.X pts/wk) or taper status,
   and projection vs goal are achievable given timeline, recovery and execution.
4. **🔍 Training Load & Adaptation Analysis**: training balance, easy vs quality execution, HRV/RHR/sleep,
   environment/travel. Mention injuries or musculoskeletal topics only when this window's data points to
   them (skipped/shortened run, pain note or comment, abnormal mechanics); completed key sessions are
   evidence the area is fine. No generic injury section or reminder.
5. **🧭 North Star Progress** (goal plans only): block status, equivalents trend and gap, and whether the
   block builds or erodes what the north star needs.
6. **🚀 Top 2 Priorities for the Upcoming Week**: at most 2 ranked actions, each one or two specific
   sentences (session/day, pace/HR/volume or recovery target) tied to the evidence. One if only one
   matters. No generic reminders.
