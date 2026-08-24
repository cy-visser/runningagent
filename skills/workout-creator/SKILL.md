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

3. **Execute Workout / Note Tool**:
   - **For Workouts (Both New Sessions AND Modifications/Updates)**:
     - Always call the `create_workout` Python tool directly. Do NOT attempt to run scripts or execute code.
     - `create_workout` is the single unified facade: it automatically checks if an existing planned workout exists on the specified date and updates it in TrainingPeaks, or creates a new workout if none exists.
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

4. **Deliver Workout / Note Confirmation**:
   - Always use clean plain text and standard Markdown for numbers, units, transitions, and metrics. Never use LaTeX syntax or dollar-sign delimiters (`$...$`).
   - Present a clean, motivational summary formatted in Markdown:
     1. **🎯 Confirmation Header**: Clear confirmation of the scheduled/updated workout or note.
     2. **📋 Workout / Note Overview Table**: Date, Sport, Title, Planned Duration / Distance, and Estimated TSS.
     3. **🏃 Coaching Directives & Execution Details**: Key pacing targets, HR zones, warm-up/cool-down structure, and fueling notes.
     4. **💡 Proactive Coaching Tip**: 1-2 actionable tips tailored to the session (e.g., hydration reminder, weather considerations, or pairing with next day's recovery).
