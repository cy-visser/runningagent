---
name: plan-audit
description: Audits scheduled weekly volume, TSS, intensity spacing, long runs, travel notes, and taper compliance.
---

# Plan Audit & Assessment Skill

## Protocol

1. **Retrieve Data**:
   - Call `fetch_plan_audit_data` in the same step as `load_skill` (defaults: `weeks_forward=4`, `weeks_back=1`). Pass explicit `start_date` / `end_date` verbatim whenever the runner specifies a window.
   - Use pre-computed weekly km, TSS, easy/quality counts, `📈 Volume`, and `🏃 Long run` facts as-is—never re-sum sessions.

2. **Evaluate Risk & Goal Alignment**:
   - **Volume & TSS Progression**: judge each week's `📈 Volume` (`vs prior week` and `vs path`) against CTL vs goal CTL range, recently held weekly km and long-run history, training background, same-week quality/long-run load, down-week spacing (every 4th build week is a `recovery week` by design—neither its dip nor the return to path next week is a ramp error), and travel/illness/niggle notes. State the % and runner-specific rationale when flagging a steep ramp or approving one. Interpret `vs path` (well below erodes north-star base; above block target is excess volume; recovery/taper above path isn't recovering; completed/transition/race weeks have no path).
   - **Intensity & Spacing**: check hard-session count and >= 48 h spacing for this runner's CTL, phase, goal distance, and north-star long-run protection; cite specific sessions and dates on conflicts.
   - **Long Runs**: no fixed cap or generic distance range—progress from recent `Long-run history`, weekly volume share (raise weekly volume first when it limits the long run), block phase, and weeks to goal/north star.
   - **Travel, Notes & Taper**: align volume/intensity with calendar travel, climate/treadmill constraints, and stress notes; judge taper depth from recent load and race distance to shed fatigue while keeping sharpness.

## Output

The web calendar already displays every scheduled session, weekly km/TSS, and note—**do not repeat sessions, weekly totals, or notes, and write no intro or closing prose.** Resolve competing trade-offs on the same week into a single weighed verdict (never flag opposite sides as separate risks). Output **only** these two sections:
- `### Assessment` — 3-5 bullets starting with `🟢` / `🟡` / `🔴` covering key strengths and risks (ramp steps, hard-day spacing, long-run progression vs history, travel conflicts, taper).
- `### Recommendations` — concrete adjustments (with a north star, group into **Sub goal** and **North star** bullets), including a week-by-week long-run km progression across the audited window (e.g. `Dec 06 18 km -> Dec 13 20 km -> Dec 20 16 km (recovery)`) with a brief clause on why.
