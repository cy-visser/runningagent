---
name: workout-creator
description: Creates or updates planned workouts and calendar notes (<= 10 changes), staged for Update TrainingPeaks.
---

# Workout & Calendar Note Creator Skill

## Protocol

1. **Resolve Target Sessions**:
   - Format dates as `YYYY-MM-DD` (or `YYYY-MM-DDTHH:MM:SS` when a specific time is requested).
   - Reuse `[workout_id]`s already in this conversation; otherwise `stage_workout_changes` resolves by `date_str` + `sport` (`create: true` adds a session, e.g. strength on a run day). Never call a report tool to look sessions up.
   - Changes > 10 workouts belong to `plan-builder`: call `load_skill(skill_name="plan-builder", start_date=..., end_date=..., mode="overhaul")`.

2. **Weigh the Week & Stage Once**:
   - Keep internal reasoning brief—never re-sum sessions or draft raw JSON in thoughts.
   - Check intensity spacing (>= 48 h), quality load, volume step, taper, and notes; state any real risk with numbers in `message`.
   - Call `stage_workout_changes(changes=[...], message="...")` once with the complete set (`message` <= 80 words: 1-2 short sentences, or a 1-line lead + 1-3 concise bullets—prefixing real load/spacing risks or pushbacks with `⚠️` or `🔴`; ends the turn—never write duplicate prose, never list staged changes shown on the card, and never ask "shall I update TrainingPeaks?").
   - Removals use `delete: true` (`workout_id`, or `date_str` + `sport`; notes: `kind: "note"`, `date_str`, `title`).
   - If `ambiguous` is returned, ask which candidate to edit, then re-stage the full set. If the runner later approves in chat, call `apply_staged_changes()`.

3. **Session Codes (`code`, Default — Use Whenever Possible)**:
   - Pass `code` instead of raw `structure` JSON for any standard Run, Bike, Strength, or Cross-training create or rewrite (`{"date_str": "2026-11-18", "code": "T 2x15' r2'"}`). The app compiles exact builders, runner zone paces, warm-ups/cool-downs, strides (keeping existing custom strides on updates, or `strides: false` to drop), descriptions, `distance_km`, `duration_minutes`, and `tss_planned` automatically—**omit `distance_km`, `duration_minutes`, `tss_planned`, and `structure` when `code` is given** (pass `title` or compact `description` <= 70 words only when custom cues are needed).
   - Lengths: km (`8`, `1k`, `1.5k`), metres (`400m` or bare `>= 50` like `200`), time (`50'`, `90"`, `2'30"`, `1h30`), reps (`6x1k`), recoveries (`r2'`, `r90"`, `r200`), optional slot (`am` / `mid` / `pm`).
   - Codes:
     - Easy / Recovery / Long: `E 8` / `E 50'` (`+strides` adds strides at end), `R 6`, `L 22` / `L 24 +6@M` (`@M`, `@HM`, `@10K`, `@T`).
     - Quality (auto 15' WU + strides + 10' CD): `T 2x15' r2'` / `T 20'`, `I 6x1k r2'`, `Rp 10x200 r200`, `M 12k` / `M 3x5k r1k`, `P 4x2k@HM r2'` (`@5K`|`@10K`|`@HM`|`@M`), `H 8x60" r90"`.
     - Bike / Strength / Cross: `B 60' Z2` (`Z1`–`Z3`), `B 4x8' @SS r4'` (`@SS`|`@T`|`@VO2`), `S 40' heavy-lower` (`heavy-lower`|`full`|`core-hips`|`plyo`|`mobility`), `X 40' swim` (`swim`|`walk`|`crosstrain`).

4. **Custom Workout Builder (`structure`, Fallback Only)**:
   - Use `structure` **only** when the runner specifies custom warm-up/cool-down lengths, multi-zone ladders/pyramids that a single `code` cannot express, or a surgical step edit to `current_structure` (moves, renames, description-only edits, and Strength need no `structure`). **Omit `distance_km`, `duration_minutes`, and `tss_planned`**—they are derived from `structure`.
   - Schema: `{"steps": [step | repetition, ...]}` (`"primaryIntensityMetric": "percentOfThresholdHr"` for HR-led runs; Bike uses `percentOfFtp` with `duration_seconds`).
     - Step: `name`, `intensityClass` (`warmUp` | `active` | `rest` | `coolDown` | `other`), one of `distance_m` or `duration_seconds`, and for `active` steps either `pace` (`"4:25-4:35"` /km) or `intensity_min` + `intensity_max` (% threshold; optional on `warmUp`/`coolDown`/`rest`).
     - Repetition: `{"type": "repetition", "reps": 5, "steps": [work, recovery]}` (no nesting).
   - On `needs_structure`: ready items from this turn are kept automatically—re-send **only** the flagged item(s) using `code` or complete `structure` (copying untouched blocks from `current_structure` verbatim) without asking the runner.
