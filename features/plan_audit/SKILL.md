---
name: plan-audit
description: Audits scheduled weekly volume, TSS, intensity spacing, long runs, travel notes, and taper compliance.
---

# Plan Audit & Assessment Skill

## Protocol

1. **Retrieve Data**:
   - Call `fetch_plan_audit_data` in the same step as `load_skill` (defaults: `weeks_forward=4`, `weeks_back=1`). Pass explicit `start_date` / `end_date` verbatim whenever the runner specifies a window.
   - Use pre-computed weekly km, `vs prior`, `path` / `vs path`, `TSS`, `E/Q` split, and `LR` facts as-is—never re-sum sessions.

2. **Evaluate Risk & Goal Alignment**:
   - **Volume & TSS Progression**: judge each week's km (`vs prior` and `vs path`) against CTL vs goal CTL range, recently held weekly km and longest-run history, training background, same-week quality/long-run load, down-week spacing (every 4th build week is a `recovery week` by design—neither its dip nor the return to path next week is a ramp error), and travel/illness/niggle notes. State the % and runner-specific rationale when flagging a steep ramp or approving one. Interpret `vs path` (well below erodes north-star base; above block target is excess volume; recovery/taper above path isn't recovering; completed/transition/race weeks have no path).
   - **Intensity & Spacing**: check hard-session count and >= 48 h spacing for this runner's CTL, phase, goal distance, and north-star long-run protection; cite specific sessions and dates on conflicts.
   - **Long Runs**: no fixed cap or generic distance range—progress from recent `longest runs` history, weekly volume share (`LR`), block phase, and weeks to goal/north star (raise weekly volume first when it limits the long run).
   - **Travel, Notes & Taper**: align volume/intensity with calendar travel, climate/treadmill constraints, and stress notes; judge taper depth from recent load and race distance to shed fatigue while keeping sharpness.

## Output

Keep internal reasoning brief—never re-sum sessions or draft week-by-week prose. The web calendar already displays every session title, weekly km/TSS, and note—**never quote full workout titles or repeat weekly totals/notes, write no intro or closing prose, and keep the entire reply <= 200 words.** Refer to sessions compactly by date + type (e.g. `Nov 21 evening S&C`, `Dec 01 400s`). Resolve competing trade-offs on the same week into a single weighed verdict (never flag opposite sides as separate risks), and do not repeat `Assessment` rationale inside `Recommendations`. Output **only** these two sections:
- `### Assessment` — 3-5 concise bullets (`- **Topic:** ...`, 1-2 short sentences / <= 30 words each; prefix moderate risks/watchpoints with `- ⚠️ **Topic:**` and `< 48 h` spacing, taper, or unsafe ramp conflicts with `- 🔴 **Topic:**`, leaving positive/on-track bullets unmarked) covering key strengths and risks with numbers (ramp/path steps, hard-day & S&C spacing, long-run load vs history, travel/notes, taper; findings only, no fixes).
- `### Recommendations` — concrete adjustments (`<= 30 words` per bullet; with a north star, group under `- **Sub goal (<goal>):**` and `- **North star (<goal>):**` with 1-2 sub-bullets each), including a week-by-week long-run km progression across the audited window (e.g. `Dec 06 18 km -> Dec 13 20 km -> Dec 20 16 km (recovery)`) with a brief clause on why.
