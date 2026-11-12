---
name: workout-creator
description: Creates or updates planned workouts and calendar notes (<= 2 ISO weeks, <= 10 changes), staged for Update TrainingPeaks.
---

# Workout & Calendar Note Creator Skill

## Protocol

1. **Resolve Target Sessions**:
   - Format dates as `YYYY-MM-DD` (or `YYYY-MM-DDTHH:MM:SS` when a specific time is requested).
   - Reuse `[workout_id]`s already in this conversation; otherwise `stage_workout_changes` resolves by `date_str` + `sport` (`create: true` adds a session, e.g. strength on a run day). Never call a report tool to look sessions up.
   - Changes > 10 workouts or spanning >= 3 ISO weeks belong to `plan-builder`: call `load_skill(skill_name="plan-builder", start_date=..., end_date=..., mode="overhaul")`.

2. **Coaching & Prescription Rules**:
   - **Easy / Recovery**: Zone 1/2 HR discipline, conversational pace.
   - **Quality Runs**: 10-15 min warm-up + 4x(20" stride / 40" jog) + main set with target pace/HR and recoveries + 10 min cool-down.
   - **Long Runs**: steady/progressive pacing, hydration, intra-run fueling (gels/carbs every 30-45 min).
   - **Strength & Cross-Training**: specify focus (core/hips, heavy lower, mobility, Z1-Z2 ride) aligned with the profile block's training times and recovery state.
   - **TSS**: estimate when known (Easy ~50-60/hr, Tempo ~70-80/hr, Intervals ~85-100/hr).
   - **`description` Conciseness (<= 70 words per workout)**: write scannable, compact cues—1-line warm-up, concise `sets x reps @ target/RPE (rest)` bullets without narrative essays, 1-line cool-down.

3. **Weigh the Week & Stage Once**:
   - Check intensity spacing, quality load, volume step, taper, and notes; state any real risk with numbers in `message`.
   - Call `stage_workout_changes(changes=[...], message="...")` once with the complete set (`message` ends the turn—never write duplicate prose or list changes, and never ask "shall I update TrainingPeaks?").
   - Removals use `delete: true` (`workout_id`, or `date_str` + `sport`; notes: `kind: "note"`, `date_str`, `title`).
   - If `ambiguous` is returned, ask which candidate to edit, then re-stage the full set. If the runner later approves in chat, call `apply_staged_changes()`.

4. **Workout Builder (`structure`)** — required for Run/Bike creates and distance/duration/content edits (moves, renames, description-only edits, and Strength need no `structure`):
   - `distance_km`, `duration_minutes`, and `tss_planned` are derived from `structure`; write exact reps, lengths, recoveries, and targets (nothing auto-scales).
   - Schema: `{"steps": [step | repetition, ...]}`.
     - Step: `name`, `intensityClass` (`warmUp` | `active` | `rest` | `coolDown` | `other`), one of `distance_m` or `duration_seconds`, and either `pace` (`"4:25-4:35"` /km) or `intensity_min` + `intensity_max` (% threshold).
     - Repetition: `{"type": "repetition", "reps": 5, "steps": [work, recovery]}` (no nesting).
     - HR-led runs: `"primaryIntensityMetric": "percentOfThresholdHr"`. Bike: `percentOfFtp` (default) with `duration_seconds`.
   - Strides: auto-kept on rewrites and auto-added (`4x 20"/40"`) after warm-up on tempo/threshold/interval runs unless `"strides": false` is requested.
   - Threshold example: `{"steps": [{"name": "Warm up", "intensityClass": "warmUp", "duration_seconds": 900, "pace": "5:50-6:20"}, {"type": "repetition", "reps": 4, "steps": [{"name": "Stride", "intensityClass": "active", "duration_seconds": 20, "intensity_min": 105, "intensity_max": 115}, {"name": "Jog", "intensityClass": "rest", "duration_seconds": 40, "intensity_min": 75, "intensity_max": 80}]}, {"type": "repetition", "reps": 5, "steps": [{"name": "Threshold", "intensityClass": "active", "duration_seconds": 720, "pace": "4:25-4:35"}, {"name": "Jog", "intensityClass": "rest", "duration_seconds": 120, "pace": "6:15-7:00"}]}, {"name": "Cool down", "intensityClass": "coolDown", "duration_seconds": 600, "pace": "5:50-6:20"}]}`
   - Easy example: `{"steps": [{"name": "Easy", "intensityClass": "active", "distance_m": 8000, "pace": "5:55-6:25"}]}`
   - On `needs_structure`: supply complete `structure` for each item—when `current_structure` is given, copy untouched blocks/intensities verbatim and edit only what changed—then re-stage without asking the runner.
