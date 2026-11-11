---
name: plan-builder
description: Builds a new training plan or block (any length, up to the goal race) or overhauls an existing plan spanning 3+ ISO weeks or more than 10 sessions, with running, strength and bike planned together, in one compact session-code plan that the app turns into exact TrainingPeaks workouts, staged for the runner to apply week by week.
---

# Plan Builder Skill

Use this skill to build a **new plan or block**, or to **overhaul** an existing one when the changes span
**3 or more ISO weeks or more than 10 sessions**. Single sessions and small edits (≤ 2 weeks and ≤ 10
sessions) stay with workout-creator. You plan; the app builds every workout (builders, paces, strides,
totals), compares it with the calendar and writes it. You never write workout builders here.

## Protocol

1. **Read the plan context** (`fetch_plan_context`): goal and races, constraints, zone table, recent
   training (weekly km, long runs, CTL, strength / bike frequency) and the planned calendar per week.
2. **Periodize**: phases (base → build → peak → taper), weekly volume ramp of at most ~10% from the recent
   level with a down week every 3-4 weeks, peak volume and longest long run ~2-3 weeks before the race,
   then a taper. A plan through several goal races (sub goals) treats each race as a step: short taper,
   race, a few recovery days, back to the build toward the north star.
3. **Intensity**: ~80/20 easy/hard by time; at least 48 h between quality sessions (the long run counts
   as quality when it has goal-pace work); one long run per week.
4. **Strength alongside running**, reasoned for this runner:
   - heavy lower-body strength on hard-run days (after the run, same day), so easy days stay easy;
   - heavy strength at least 48 h before the long run or a key session;
   - 2x per week in base / build, 1-2x maintenance in peak, activation only in the taper, none in race week;
   - adjust for injury history (e.g. Achilles / calf: mobility and eccentric work, no plyo early in base).
5. **Bike** as low-impact aerobic volume (Z1-Z2) or a recovery day; it counts in the weekly load (TSS),
   never in running km. Use bike intervals sparingly.
6. **Constraints**: the runner's available days, injuries, notes (travel, illness) and sub goals / north star.

## Output contract

Call `stage_training_plan` **once** with the whole plan and your `message`. Do not write the message as
separate text: the call shows it with the staged-plan card and ends the turn.
- `message`: 3-6 sentences on the plan's logic (running *and* the strength / bike setup), where it peaks,
  the taper and the main risks with their numbers. **Never list sessions**: the card shows every week.
- `plan`: `{"start_date": "YYYY-MM-DD", "mode": "new" | "overhaul", "weeks": [week, ...]}` (start_date and
  mode as in the plan context). A week:
  `{"week": 7, "phase": "build", "focus": "MP endurance; heavy strength 2x", "days": {"Mon": ["B 45' Z2",
  "S 40' heavy-lower"], "Tue": "I 6x1k r2'", "Wed": "E 10", "Thu": ["T 2x15' r2'", "S 30' core-hips"],
  "Fri": "REST", "Sat": "E 8 +strides", "Sun": "L 28 +8@M"}}`.
  Week 1 is the ISO week of start_date; days before the start (or today) are skipped. A day is one code or a
  list (a run plus strength, a double). Days you leave out have nothing planned.
- `mode`: `new` adds and updates per day and sport (other planned sessions stay); `overhaul` rewrites the
  window: planned Run / Strength / Bike sessions not in your plan are removed. `REST` always removes the
  planned Run / Strength / Bike sessions of that day. Completed workouts, notes and other sports are never
  touched (Swim / Walk / Crosstrain only on days where you plan an `X` session of that sport).
- If the result lists `errors` (nothing staged), fix those codes and call `stage_training_plan` again. Do not
  ask the runner.
- **Edits after staging** ("make week 5 easier"): `stage_training_plan(plan={"weeks": [only the changed
  weeks]}, base_staged_id=<staged_id>, message=...)` replaces just those weeks.
- The runner applies the plan with **Apply to TrainingPeaks** (the app writes week by week and confirms it).
  If they approve in chat, tell them to press the button.

## Session codes

Lengths: km as `10`, `1k`, `1.5k`, metres as `400m` or `200` (a bare number ≥ 50 is metres), time as `50'`,
`90"`, `2'30"`, `1h30`. Reps `6x1k`, recoveries `r2'` / `r90"` / `r200` / `r1k` (default 2', Rp 200 m,
hills 90"). Add `am` / `pm` to place a double. Paces come from the zone table, never write paces yourself.

| Code | Session |
|---|---|
| `E 10` / `E 50'` | Easy run (add `+strides` for 4x20" strides at the end) |
| `R 6` | Recovery run |
| `L 28` / `L 2h` / `L 28 +8@M` | Long run; `+8@M` = last 8 km at goal pace (`@M`, `@HM`, `@10K`, `@T`) |
| `T 2x15' r2'` / `T 20'` | Threshold reps / continuous tempo |
| `I 6x1k r2'` / `I 5x3' r2'` | VO2max intervals |
| `Rp 10x200 r200` | Speed reps |
| `M 3x5k r1k` / `M 12k` | Marathon-pace work |
| `P 4x2k@HM r2'` / `P 8k@10K` | Race-pace work (`@5K`, `@10K`, `@HM`, `@M`; required) |
| `H 8x60" r90"` | Hill reps (effort-based) |
| `RACE` | The goal race on that day (distance and pace from the profile) |
| `B 60' Z2` / `B 45' Z1` / `B 60' Z3` | Steady ride (% of FTP) |
| `B 4x8' @SS r4'` / `B 3x10' @T r5'` / `B 5x4' @VO2 r4'` | Ride intervals |
| `S 45' heavy-lower` | Strength; focus `heavy-lower`, `full`, `core-hips`, `plyo` or `mobility` (adjusted to the phase) |
| `X 40' swim` / `X 45' walk` / `X 30' crosstrain` | Other cross-training (duration only) |
| `REST` | Nothing that day (removes planned Run / Strength / Bike sessions) |

T, I, Rp, M and P sessions get a 15' warm-up, strides and a 10' cool-down automatically. Use `T 3x10' @HM`
to run a threshold-style session at another zone pace.
