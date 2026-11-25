---
name: plan-audit
description: Audits scheduled weekly km, TSS, hard-day spacing, long runs, notes, and taper.
---

# Plan Audit & Assessment Skill

## Evaluation (follow `GOAL REASONING`; use pre-computed weekly km, `vs prior`, `TSS`, `E/Q`, and `LR` facts as-is—never re-sum)

- **Volume & TSS**: judge weekly km and `vs prior` against 12-week history (peak, streaks, post-race/taper), CTL vs goal CTL range (and North-Star CTL trajectory over time left), same-week quality/S&C/LR load, deload weeks (neither a deload dip nor returning to prior build volume is a ramp error), and notes; state `%` and runner-specific rationale.
- **Intensity & Spacing**: judge quality load and recovery spacing across hard runs, quality LRs, and S&C for this runner's CTL, durability, phase, and goals (no generic ratio/hour cutoff); cite specific dates/sessions on conflicts.
- **Long Runs**: judge distance and internal quality from `longest runs` history, weekly `LR` share, phase, and weeks to race (no fixed cap).
- **Travel, Notes & Taper**: align load with travel/climate/stress notes; judge taper depth from recent load, race distance, and post-race North-Star continuity.
- **Race Events**: check `Race Events in Window` — verify both a TrainingPeaks Event (`A` priority for the training block's target goal; `B`/`C` — never `A` — for intermediate races) and a paired race workout exist on race days. Flag missing or mis-prioritized events with `⚠️` in `### Assessment` and recommend creating/updating them via `stage_workout_changes` in `### Recommendations`.

## Output (`<= 200 words` total, no intro/closing prose, never quote full titles or repeat weekly totals/notes)

Keep reasoning brief. Refer to sessions by `date + type` (e.g. `Dec 01 400s`), resolve same-week trade-offs into one verdict, and do not repeat `Assessment` rationale inside `Recommendations`. Output **only**:
- `### Assessment` — 3-5 bullets (`- **Topic:** ...`, `<= 30w` each; prefix moderate/high risks with `⚠️`/`🔴`, leave on-track unmarked) with numbers on ramp vs history, spacing, LR load, notes/taper, and any specific runner question (findings only, no fixes).
- `### Recommendations` — **delta-only** edits to current TrainingPeaks schedule (`<= 30w` each, `date + current -> proposed` + brief why; never list unchanged workouts; propose clean single-pattern sessions like `4x1.2km @4:08/km` rather than mixed multi-set combos unless requested). With a north star, group under `- **Sub goal (<goal>):**` and `- **North star (<goal>):**` (1-2 sub-bullets each; state if one needs no edits).
