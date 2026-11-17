---
name: plan-audit
description: Audits scheduled weekly km, TSS, hard-day spacing, long runs, notes, and taper.
---

# Plan Audit & Assessment Skill

## Protocol

1. **Retrieve Data**:
   - Call `fetch_plan_audit_data` in the same step as `load_skill` (defaults: `weeks_forward=4`, `weeks_back=1`). Pass explicit `start_date` / `end_date` verbatim whenever the runner specifies a window.
   - Use pre-computed weekly km, `vs prior`, `TSS`, `E/Q` split, and `LR` facts as-is—never re-sum sessions.

2. **Evaluate Risk & Goal Alignment** (always judge toward **both the sub-goal and the North Star** when a North Star is set, or **toward the goal** when there is no North Star):
   - **Volume & TSS Progression**: judge each week's km and `vs prior` against 12-week weekly km history (peak, sustained streaks, post-race/taper context), CTL vs the goal's CTL range (and North-Star CTL trajectory over the time left), training background, same-week quality/S&C/long-run load, intentional down/deload weeks (neither a deload dip nor returning to prior build volume next week is a ramp error), and travel/illness/niggle notes. Weigh whether volume both lets the runner recover for current-goal sessions and builds/preserves aerobic capacity for the North Star (or single goal); state the % and runner-specific rationale when flagging or approving a step.
   - **Intensity & Recovery Spacing**: judge quality-session load, intensity distribution, and recovery spacing across hard runs, quality long runs, and S&C from exercise physiology for this runner's CTL, durability, phase, and goal/North-Star demands (no fixed hour cutoff or generic ratio); cite specific sessions and dates on genuine recovery conflicts.
   - **Long Runs**: no fixed cap or generic distance range—judge distance and internal quality from recent `longest runs` history, weekly volume (`LR`), block phase, and weeks to the goal (and North Star, when set).
   - **Travel, Notes & Taper**: align volume/intensity with calendar travel, climate/treadmill constraints, and stress notes; judge taper depth from recent load and race distance to shed fatigue while keeping sharpness (and protecting North-Star continuity after a sub-goal race).

## Output

Keep internal reasoning brief—never re-sum sessions or draft week-by-week prose. The web calendar already displays every session title, weekly km/TSS, and note—**never quote full workout titles or repeat weekly totals/notes, write no intro or closing prose, and keep the entire reply <= 200 words.** Refer to sessions compactly by date + type (e.g. `Nov 21 evening S&C`, `Dec 01 400s`). Resolve competing trade-offs on the same week into a single weighed verdict (never flag opposite sides as separate risks), and do not repeat `Assessment` rationale inside `Recommendations`. Output **only** these two sections:
- `### Assessment` — 3-5 concise bullets (`- **Topic:** ...`, 1-2 short sentences / <= 30 words each; prefix moderate risks/watchpoints with `- ⚠️ **Topic:**` and high-risk load, recovery, or taper conflicts with `- 🔴 **Topic:**`, leaving positive/on-track bullets unmarked) covering key strengths and risks with numbers (ramp steps vs history, intensity & S&C spacing, long-run load vs history, travel/notes, taper; findings only, no fixes; if the runner asked a specific question—e.g. benchmark/predictor session—answer it directly in one dedicated bullet).
- `### Recommendations` — **delta-only** adjustments to what is currently scheduled in TrainingPeaks (`<= 30 words` per bullet, `date + current -> proposed` + brief clause on why; **never** list or repeat workouts/long-run progressions already in TrainingPeaks unless missing from the calendar). With a north star, group under `- **Sub goal (<goal>):**` and `- **North star (<goal>):**` (1-2 sub-bullets each; if one level needs no edits, write one sub-bullet stating no changes needed and why).
