---
name: plan-builder
description: Builds a new training block or full-block overhaul via weekly session codes.
---

# Plan Builder Skill

Builds a **new training block** or **full-block overhaul** (`stage_workout_changes` handles targeted calendar edits of any count). `load_skill("plan-builder", start_date, end_date, mode)` automatically loads `PLAN CONTEXT` (zones, recent training, weekly calendar) in the same step. You write session codes; the app builds exact workouts, builders, strides, and calendar diffs.

## Protocol

1. **Scope & Context**:
   - New plans target the **NEXT UNPLANNED GOAL** in the profile block after block intake agreement (never re-plan a `planned` goal unless asked). Overhauls (`mode="overhaul"`) need no prior intake.
   - Ground periodization, weekly volume, intensity distribution, recovery spacing, long-run progression, and strength/cross-training in `PLAN CONTEXT`, the North Star trajectory, and the runner's stated baselines and requests—decide from exercise physiology for this specific runner, goal distance, and phase rather than fixed ratios or generic caps (for future blocks after intervening blocks, anchor `W1` to the expected entry baseline rather than today's snapshot).
   - When scaling weekly volume high or bridging a 5K/10K/HM block toward a Marathon North Star, absorb the volume across run frequency, a mid-week medium-long run, and easy aerobic runs rather than scaling `L` mechanically as a `%` of weekly km—check single-run **time-on-feet at `ZONES` `L` pace** for the **current** goal distance, and trade off peak long-run duration (Base/early Build) against peak race-pace density (step total `L` distance down in Peak phase when embedding heavy `@HM`/`@10K` segments).
   - When `W1` is marked `partial` (mid-week start), schedule only the active days of `W1` and scale `W1` volume proportionally—never squeeze a full week or standalone opener long run onto a 1-2 day partial week.
2. **Workout & Slot Mechanics**:
   - Build long-run quality (fast finishes, race-pace or threshold blocks, progressive finishes, optional easy cool-down) directly into `L` with `+` segments rather than splitting those blocks onto another day's `P` session or replacing `L` with a shorter `P` workout.
   - Schedule tune-up races and organized events on their exact date with `RACE <dist> @<pace> [Name]` (raced all-out, e.g. `RACE 16k @HM Dam tot Damloop`) or `EVENT <dist> @<pace> [Name]` (controlled training effort, e.g. `EVENT 16k @M Tilburg 10mi` or `@E`)—never wrap standalone events inside `L` to pad km unless asked, and never code standalone races/events as `P`/`M`/`T` (those auto-add 15' WU + strides + 10' CD).
   - **Race Calendar Events (`plan["events"]`)**: Every block's target race AND every intermediate `RACE`/`EVENT` in the block needs BOTH the workout code AND a TrainingPeaks Calendar Event in `plan["events"]`:
     - `{"date": "YYYY-MM-DD", "name": "...", "event_type": "RunningRoad"|"RunningTrail"|"RunningTrack"|"RunningCrossCountry"|"RunningOther", "distance_km": <float>, "race_type_duration": "RunUnderOneHour"|"RunOnetoTwoHours"|"RunOverTwoHours", "priority": "A"|"B"|"C", "goal_time": "H:MM:SS"|"MM:SS"|null, "goal_place": <int>|null, "goal_pr": true|false|null}`.
     - Block target race = **`A`** priority; intermediate races within the block = **never `A`** (reason **`B`** for a key tune-up race vs **`C`** for a controlled/training event).
     - Derive `distance_km`, `race_type_duration` (`0–1h` → `RunUnderOneHour`, `1–2h` → `RunOnetoTwoHours`, `2+h` → `RunOverTwoHours`), and `goal_time` from the training block's goal (e.g. `sub 21 5k` → `5.0`, `RunUnderOneHour`, `21:00`); set `goal_place` (integer) and `goal_pr` (boolean) strictly from your conversation with the runner (omit/`null` if not discussed).
   - Follow **Training times** in `PLAN CONTEXT` automatically (do not add `am`/`mid`/`pm` unless asked to reorder).
   - Bike (`B`) adds low-impact TSS without counting toward running km.

## Output Contract

Keep internal reasoning brief—do not draft week-by-week tables, re-audit unchanged weeks, or sum km in thoughts; the app computes exact km and TSS. Call `stage_training_plan` **once** with `plan` and `message` (ends the turn; never write separate text):
- `message`: Telegraphic plain-chat Markdown—the interactive agenda card below already shows every week, km/TSS, and session, so **never restate the schedule or intake summary**:
  - **Initial plan / overhaul (`### Block Strategy`, <= 120 words total)**: 1 short lead sentence (<= 20 words), then 3-4 single-sentence numbered items (<= 22 words each; omit #3 if no strength/bike):
    1. `**Volume & Long Runs:**` start -> peak km, down-week rhythm, peak long run, taper.
    2. `**Intensity & Rhythm:**` quality anchors and easy/rest spacing.
    3. `**Strength & Cross-Training:**` pairing with runs and peak/taper step-down.
    4. `**Watchpoints:**` 1-2 short `- ⚠️ ` sub-bullets (<= 18 words each) on concrete load/injury/goal guardrails.
  - **Revisions (`### Plan Update`, delta-only, <= 90 words; <= 120 words if pushing back)**: **never repeat unchanged pillars or weeks**. Write 1 short lead sentence stating what changed, plus 1-3 single-sentence numbered items (<= 25 words each; prefix physiological pushbacks/conflicts with `⚠️` or `🔴`) covering only what applies: physiological pushback/compromise (with numbers + 1-clause override offer), ripple shifts to protect recovery, and execution guardrails for added races/key sessions (for trivial 1-2 session tweaks, skip bullets—1-2 sentences total).
  - **NO Markdown tables** and **NO week-by-week or session lists**.
- `plan`: `{"start_date": "YYYY-MM-DD", "mode": "new" | "overhaul", "weeks": ["W1 | base | Aerobic base; 2x strength | Mon: B 45' Z2; S 40' heavy-lower | Tue: I 6x1k r2' | Sun: L 24", ...]}` (`W1` = ISO week of `start_date`; separate multiple sessions on one day with `;`; keep `focus` <= 6 words).
- `mode`: `"new"` adds/updates per day+sport; `"overhaul"` also removes unlisted planned Run/Strength/Bike sessions in the window. **Omit rest days in `"new"` mode** unless clearing an existing planned workout on that day (`REST` deletes planned Run/Strength/Bike on that day; omitted days automatically show as Rest on the agenda). Completed workouts and notes are untouched.
- On `errors`: fix the flagged codes and call `stage_training_plan` again without asking the runner.
- **Edits after staging**: call `stage_training_plan(plan={"weeks": [changed weeks]}, base_staged_id=<staged_id>, message=...)` passing **only** the changed weeks (omit unchanged weeks; never call `load_skill("plan-builder")` again for the same window). If approved in chat, tell the runner to press **Apply to TrainingPeaks**.

## Session Codes

Lengths: km (`10`, `1k`, `1.5k`), miles (`10mi`), metres (`400m` or bare `>= 50` like `200`), time (`50'`, `90"`, `2'30"`, `1h30`). Reps `6x1k`, recoveries `r2'` / `r90"` / `r200` / `r1k` (defaults: `2'`, `Rp` `200m`, `H` `90"`). Optional slot override: `am` / `mid` / `pm`. Never write paces yourself.

| Code | Session |
|---|---|
| `E 10` / `E 50'` | Easy run (`+strides` adds 4x20" strides at end) |
| `R 6` | Recovery run |
| `L 28` / `L 28 +8@M` / `L 36 +4x7k@M r1k +2@E` | Long run (total km/time); `+` segments append in order (e.g. `+6@HM`, `+4x4k@HM r1k`, optional `+2@E`/`+2@L` cooldown) |
| `T 2x15' r2'` / `T 20'` | Threshold reps / tempo (`T 3x10' @HM` uses another zone) |
| `I 6x1k r2'` / `I 5x3' r2'` | VO2max intervals |
| `Rp 10x200 r200` | Speed reps |
| `M 3x5k r1k` / `M 12k` | Marathon-pace work |
| `P 4x2k@HM r2'` / `P 8k@10K` | Race-pace work (`@5K`, `@10K`, `@HM`, `@M` required) |
| `H 8x60" r90"` | Hill reps |
| `RACE` / `RACE 16k @HM [Name]` | Goal race on that day (`RACE`), or tune-up race at exact distance & effort (no auto WU/CD) |
| `EVENT 16k @M [Name]` | Organized event at controlled pace (`@M`, `@T`, `@E`; exact distance, no auto WU/CD) |
| `B 60' Z2` / `B 45' Z1` / `B 60' Z3` | Steady ride (% FTP) |
| `B 4x8' @SS r4'` / `B 3x10' @T r5'` / `B 5x4' @VO2 r4'` | Ride intervals |
| `S 45' heavy-lower` | Strength (`heavy-lower`, `full`, `core-hips`, `plyo`, `mobility`) |
| `X 40' swim` / `X 45' walk` / `X 30' crosstrain` | Cross-training (duration only) |
| `REST` | Clears planned Run / Strength / Bike that day |

`T`, `I`, `Rp`, `M`, and `P` include a 15' warm-up, strides, and 10' cool-down automatically (`RACE` and `EVENT` do not).
