---
name: check-in-report
description: Short-horizon (last 14 days + next 7) check-in on training execution, recovery, CTL/LT trajectory, and next-week priorities.
---

# Check-In Report Skill

Call `fetch_checkin_data` in the same step as `load_skill`. Follow `GOAL REASONING` in your instructions; include **North Star Progress** only for goal plans (skip for single goals).

## Analysis Pillars

1. **Intensity & Execution**: Separate easy/recovery Zone 1/2 discipline from structured quality (tempo, intervals, MP, races); judge weekly `Split` for this runner and goal distance.
2. **Volume**: Judge `Volume vs prior week` against CTL, recently held volume, training background, and HRV/RHR/sleep. Flag overuse risk only with its % and runner-specific rationale. Treat cutback/return-to-baseline weeks normally, and never flag `Partial week` rows as spikes/drops.
3. **Physiology & Environment**: Weigh load (`TSB`, `ATL:CTL`—reasoning only, never table rows) against HRV, RHR, sleep (`5-day vs 28-day baseline`) and the listed recent hard effort (days ago, km, TSS) plus heat, humidity, travel, and **Calendar Notes** to distinguish normal recovery from overreaching or illness/stress.
4. **Goal Trajectory**:
   - **LT1 / LT2 pace** (4-wk vs prior 4-wk): weigh the threshold most relevant to the goal (LT2 + LT1 base for 5K/10K; CTL + LT1 for HM/M). `(HR outside the fitted HR range: extrapolated)` = lower confidence; note when steady laps are insufficient.
   - **Required CTL build** (pts/wk to taper) vs **Taper phase**: judge build realism against historical CTL absorption and weeks left (suggest timeline/volume/goal change if unrealistic). In taper, CTL drops by design—judge freshness vs sharpness from banked peak CTL, TSB, recovery markers, and race-pace touches; never cram load.
   - **Projection & Trust** (`Today -> Race day`, **Projection drivers**, `Evidence:`): cite limiting drivers and session dates (`Goal-pace work`, `Threshold anchor`), interpret `Today -> Race day` with TSB, and judge projection confidence (propose a specific test/threshold session only if warranted now; note `Insufficient recent run data` / `No race distance in goal` plainly).
   - Distinguish planned cutbacks from falling behind; assign **On Track**, **Build Focus Needed**, or **Adjustment Recommended**.
5. **North Star** (goal plans only): Evaluate sub-goal equivalents (`GOAL PLAN` table) and current projection against north-star needs (CTL trajectory given time remaining, long-run durability, volume). If a finished sub goal shows `missing: ask the runner`, ask how it went and offer `analyze_workout` for that date (or ask to sync it).

## Output

The web card already renders all metrics, projections, drivers, PMC chart, and weekly totals—**write no overview or tables, quote numbers only to back a judgement, and keep the entire reply <= ~180 words.** Use exact `###` headings in order:
1. `### 🎯 Goal Trajectory Status`: 1-2 concise sentences stating the verdict (**On Track** / **Build Focus Needed** / **Adjustment Recommended**) + whether CTL, ramp (`+X.X pts/wk`) or taper, and projection vs goal are on track.
2. `### 🔍 Training Load & Adaptation Analysis`: 2-3 concise `- ` bullets (`<= 25 words` each; prefix genuine load, recovery, or injury issues with `⚠️` or `🔴`, leaving on-track bullets unmarked) covering intensity balance/execution, HRV/RHR/sleep, and environment/notes. Mention injuries/mechanics only when this window's data shows an issue (pain note, skipped/cut run, abnormal metrics)—no generic reminders.
3. `### 🧭 North Star Progress` (goal plans only): 1-2 concise sentences or bullets on block status, equivalents trend/gap, and whether this block builds or erodes north-star readiness.
4. `### 🚀 Top 2 Priorities for the Upcoming Week`: 1-2 numbered one-sentence items (`1.`, `2.`, <= 25 words each: day/session + pace/HR/volume/recovery target tied to evidence).
