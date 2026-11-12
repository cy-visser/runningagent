---
name: plan-builder
description: Builds a new training plan/block or overhauls >= 3 ISO weeks / > 10 sessions using compact session codes, applied week by week.
---

# Plan Builder Skill

Builds a **new plan/block** or **overhauls** >= 3 ISO weeks / > 10 sessions (`<= 2` weeks and `<= 10` sessions use `workout-creator`). `load_skill("plan-builder", start_date, end_date, mode)` automatically loads `PLAN CONTEXT` (zones, recent training, weekly calendar) in the same step. You write session codes; the app builds exact workouts, builders, strides, and calendar diffs.

## Protocol

1. **Scope & Agreement**:
   - New plans target the **NEXT UNPLANNED GOAL** in the profile block after block intake agreement (never re-plan a `planned` goal unless asked). Overhauls (`mode="overhaul"`) need no prior intake.
   - Weigh `PLAN CONTEXT` (recent weekly km, long runs, CTL, strength/bike frequency, calendar notes) and `KEY EVENTS` (recent races, injuries, breaks).
2. **Periodize & Balance**:
   - Progress phases (`base -> build -> peak -> taper`) from recent held volume at a runner-appropriate ramp with down weeks every 3-4 weeks; peak ~2-3 weeks pre-race, then taper. Treat sub-goal races as steps (mini-taper, race, short recovery, resume build toward north star).
   - Keep ~80/20 easy/hard by time, >= 48 h between quality sessions (goal-pace long runs count as quality), and one long run/week.
3. **Strength & Bike**:
   - Follow **Training times** in `PLAN CONTEXT` (do not add `am`/`mid`/`pm` unless asked to reorder).
   - Run before strength (or unset): place `heavy-lower` on hard-run days so easy days stay easy. Strength before run: put `heavy-lower` on easy days (>= 6 h gap) and `core-hips`/`mobility` on quality days. Keep heavy lower >= 48 h before long/key runs.
   - Frequency: 2x/wk base/build, 1-2x maintenance in peak, activation in taper, none race week. Adapt to injury history (e.g. calf/Achilles: eccentric/mobility before plyo).
   - Bike (`Z1-Z2`) adds low-impact TSS (never running km); use bike intervals sparingly.

## Output Contract

Call `stage_training_plan` **once** with `plan` and `message` (ends the turn; never write separate text or list sessions):
- `message`: 3-6 sentences covering progression logic, strength/bike fit with training times, peak, taper, and numeric risks.
- `plan`: `{"start_date": "YYYY-MM-DD", "mode": "new" | "overhaul", "weeks": [{"week": 1, "phase": "base", "focus": "...", "days": {"Mon": ["B 45' Z2", "S 40' heavy-lower"], "Tue": "I 6x1k r2'", "Fri": "REST", "Sun": "L 24"}}]}` (`week: 1` = ISO week of `start_date`).
- `mode`: `"new"` adds/updates per day+sport; `"overhaul"` also removes unlisted planned Run/Strength/Bike sessions in the window. `REST` clears planned Run/Strength/Bike on that day. Completed workouts and notes are untouched.
- On `errors`: fix the flagged codes and call `stage_training_plan` again without asking the runner.
- **Edits after staging**: `stage_training_plan(plan={"weeks": [changed weeks]}, base_staged_id=<staged_id>, message=...)`. If approved in chat, tell the runner to press **Apply to TrainingPeaks**.

## Session Codes

Lengths: km (`10`, `1k`, `1.5k`), metres (`400m` or bare `>= 50` like `200`), time (`50'`, `90"`, `2'30"`, `1h30`). Reps `6x1k`, recoveries `r2'` / `r90"` / `r200` / `r1k` (defaults: `2'`, `Rp` `200m`, `H` `90"`). Optional slot override: `am` / `mid` / `pm`. Never write paces yourself.

| Code | Session |
|---|---|
| `E 10` / `E 50'` | Easy run (`+strides` adds 4x20" strides at end) |
| `R 6` | Recovery run |
| `L 28` / `L 2h` / `L 28 +8@M` | Long run; `+8@M` = last 8 km at `@M`, `@HM`, `@10K`, or `@T` |
| `T 2x15' r2'` / `T 20'` | Threshold reps / tempo (`T 3x10' @HM` uses another zone) |
| `I 6x1k r2'` / `I 5x3' r2'` | VO2max intervals |
| `Rp 10x200 r200` | Speed reps |
| `M 3x5k r1k` / `M 12k` | Marathon-pace work |
| `P 4x2k@HM r2'` / `P 8k@10K` | Race-pace work (`@5K`, `@10K`, `@HM`, `@M` required) |
| `H 8x60" r90"` | Hill reps |
| `RACE` | Goal race on that day |
| `B 60' Z2` / `B 45' Z1` / `B 60' Z3` | Steady ride (% FTP) |
| `B 4x8' @SS r4'` / `B 3x10' @T r5'` / `B 5x4' @VO2 r4'` | Ride intervals |
| `S 45' heavy-lower` | Strength (`heavy-lower`, `full`, `core-hips`, `plyo`, `mobility`) |
| `X 40' swim` / `X 45' walk` / `X 30' crosstrain` | Cross-training (duration only) |
| `REST` | Clears planned Run / Strength / Bike that day |

`T`, `I`, `Rp`, `M`, and `P` include a 15' warm-up, strides, and 10' cool-down automatically.
