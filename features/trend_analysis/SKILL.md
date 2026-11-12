---
name: trend-analysis
description: Long-horizon (6+ weeks) training-log analysis of fitness progress, weekly load capacity, pacing headroom, and block recommendations.
---

# Trend Analysis Skill

Call `fetch_trend_data` in the same step as `load_skill` (pass `weeks` only when the runner specifies a horizon, e.g. `"since July"`). The web card renders all charts and tables; you synthesize the evidence into ranked next-block recommendations following `GOAL REASONING`.

## Internal Analysis Dimensions (do not output as sections)

- **Goal Context**: Projection vs goal (gap + evidence recency), CTL vs peak target and required ramp, weeks to race, and (for goal plans) north-star equivalent/gap and sub-goal progression.
- **Progress**: First-to-last week shifts in CTL, rolling 4-wk **Pace @ LT1** / **Pace @ LT2** (`*` = extrapolated; weigh LT2 with the **LTHR check** sustained 20+ min effort), **Key-run Pa:Hr %** (lower = less drift on goal-specific key sessions), and HRV/RHR/sleep (`Higher is better` column). Judge statistical/practical significance by sample weeks and magnitude.
- **Load Capacity**: Weigh `volume-levels` streaks, HRV/RHR deltas, RPE, and niggle comments against the `Weekly volume reference` path. Unheld or niggle-heavy mileage is weak capacity evidence—state how far any target exceeds proven volume and the runner-specific weekly ramp you assumed.
- **Pacing**: Check easy-pace discipline and per-band workout headroom (target hit rate, median pace/HR, `%LTHR`, `Pa:Hr`, and `HR->pace slope` in s/km per `+1% LTHR`). Anchor paces on threshold evidence, never goal time; if LTHR confidence is low, suggest a verification effort only if relevant now.
- **Patterns & Long Runs**: Treat session-mix / long-run-share / sleep correlations as associations (check `n=`). Progress long runs from `Long-run history`, weekly volume, and race timeline—never jumps or generic caps. Use raw athlete comments for niggle/fatigue context.

## Output

**Write no overview, tables, or dimension sections, and do not restate chart values.** Output only:

1. `### 🎯 Next Block: Top 3`: exactly 3 numbered recommendations ranked by goal impact, each formatted as:
   - **Bold, concrete action** (weekly km, long-run km, min/km paces, session mix, or test), followed by
   - `Why:` one line citing exact tool numbers (e.g. weeks held + km gap, hit rate at `%LTHR`, LT/CTL delta, projection gap).
2. `### 🧭 North Star` (goal plans only): 1-3 numbered recommendations in the same format covering what this block must protect/build for the north star (CTL trajectory vs peak range, long-run progression from history, volume toward block/north-star target), quoting the north-star equivalent and gap once.

If the coverage line notes unrecorded workouts, append one italic sentence noting those weeks are incomplete and re-running later will fill them in.
