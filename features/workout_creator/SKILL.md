---
name: workout-creator
description: Creates, schedules, or modifies planned workouts, training sessions, and calendar notes in TrainingPeaks based on coaching guidelines, periodization, and runner goals.
---

# Workout & Calendar Note Creator Skill

You are now equipped with the Workout & Calendar Note Creator skill. Use this skill when the runner asks you to create, schedule, add, plan, change, or modify workouts, training runs, cross-training sessions, or calendar notes in TrainingPeaks.

## Protocol:

1. **Understand & Classify the Request**:
   - **Target Date**: Determine the workout or note date. Always format as ISO `YYYY-MM-DD` (or ISO datetime `YYYY-MM-DDTHH:MM:SS` if a specific time of day is requested).
   - **Type of Entry**:
     - **Planned Workout (Create or Modify)**: Run (easy, recovery, tempo, threshold, intervals, long run, race pace, progressive), Bike, Swim, Strength, Walk, Crosstrain, Race.
     - **Calendar Note**: Travel plans, rest/recovery days, race prep checklist, nutrition/carb-load reminder, illness/injury note, or milestone markers.

2. **Apply Sports Science & Coaching Principles**:
   - **Easy / Recovery Runs**: Zone 1/2 HR discipline, conversational pace, low aerobic stress.
   - **Quality / Structured Workouts**:
     - Prescribe specific warm-up (10-15 min easy + dynamic drills/strides).
     - Define main set intervals, target pace zones, or HR thresholds.
     - Prescribe recovery intervals between reps.
     - Prescribe cool-down (10 min easy).
   - **Long Runs**: Include pacing guidance (starting easy, holding steady), hydration strategy, and intra-workout fueling cadence (gels/carbs every 30-45 min).
   - **Strength & Cross-Training**: Specify focus (core, hips, glute activation, low-impact cross-training).
   - **TSS Estimation**: If duration and intensity are known, estimate planned TSS (e.g., Easy Run ~50-60 TSS/hr, Tempo ~70-80 TSS/hr, Hard Intervals ~85-100 TSS/hr).

3. **Load Warnings (built into `create_workout`, advisory only)**:
   - When the runner asks to create or update a workout, do it: call `create_workout` straight away. Never
     ask for confirmation before writing and never hold back an update the runner requested.
   - For run and race sessions `create_workout` also checks the change in code against the target week and
     the prior week (3rd+ quality session, hard sessions on consecutive days, quality inside the goal race's
     taper, quality or long runs near an injury/illness calendar note). It only reports risks the change
     introduces or worsens. Do not fetch the schedule yourself to check this.
   - If the result contains `warnings`, the workout WAS written. State each warning **with its numbers** in
     the confirmation and offer one specific safer alternative (e.g. "move it to Thursday and drop Tuesday
     to easy") the runner can ask for.
   - **Weekly volume ramp (your judgement, no coded % limit)**: when the change adds running km, the result
     carries `week` (`running_km_after`, `prior_week_running_km`, `volume_change_pct`). Judge whether that
     step suits this runner from their CTL, recent weekly volume, training age and race background (e.g.
     previous marathon builds) and what else is in the week. Mention it under Load Warnings only if you judge
     it a real risk, with the numbers and the runner-specific reason; never cite a generic "10% rule".

4. **Execute Workout / Note Tool**:
   - **For Workouts (Both New Sessions AND Modifications/Updates)**:
     - Call `create_workout`. Choose the mode explicitly:
       - **Adding** a session to a day (e.g. strength on a run day, a double): pass `create=True`.
       - **Changing a specific** existing session: pass its `workout_id`.
       - Otherwise it updates the single planned workout of the same sport on that date, or creates one if there is none. Other sports on that day are never touched.
     - If it returns `"action": "needs_workout_id"`, ask the runner which of the listed `candidates` to change (or whether to add a new one) and call again with `workout_id` or `create=True`.
     - Pass the following arguments:
       - `date_str`: Target date in `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`.
       - `sport`: Sport type (default `"Run"`).
       - `title`: Clear, descriptive workout title (e.g. `"Easy Aerobic Recovery Run"`, `"Threshold Intervals: 5x1km"`).
       - `duration_minutes`: Estimated planned duration in minutes.
       - `distance_km`: Optional planned distance in kilometres.
       - `tss_planned`: Optional planned TSS.
       - `description`: Structured coaching instructions with warm-up, main set, cool-down, and pacing cues.
   - **For Calendar Notes (Non-Workout Calendar Entries)**:
     - Call `create_note` with:
       - `date`: Target date in `YYYY-MM-DD`.
       - `title`: Clear note title (e.g., `"Travel: Flight to Milan"`, `"Rest Day & Foam Rolling"`).
       - `description`: Optional detailed notes or advice.

5. **Deliver Workout / Note Confirmation**:
   - Present a clean, structured summary in Markdown:
     1. **🎯 Confirmation Header**: Clear confirmation of the scheduled/updated workout or note.
     2. **📋 Overview Table**: Date, Sport, Title, Planned Duration / Distance, and Estimated TSS.
     3. **🏃 Coaching Directives & Execution Details**: Pacing targets, HR zones, warm-up/cool-down structure, and fueling cues.
     4. **⚠️ Load Warnings** *(only when the result contains `warnings` or you judge the volume ramp a real risk for this runner)*: Each warning with its numbers and one safer alternative.
     5. **💡 Proactive Coaching Tip**: Specific tip tailored to the session (hydration, weather, recovery pairing).

