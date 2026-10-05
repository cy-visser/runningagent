---
name: workout-analysis
description: Performs a deep, structured physiological analysis of a single completed workout/run.
---

# Workout Analysis Skill

You are now equipped with the Workout Analysis skill. Use this skill when the runner asks to analyze a specific **run** or **running workout**. *(Note: For completed cycling/biking workouts, route to the `bike-workout-analysis` skill.)*

## Protocol:

1. **Gather Data**:
   - Call `analyze_workout` (e.g. `analyze_workout(date_str="today", sport="run")` or `analyze_workout(workout_id="<id>")`). This tool automatically retrieves the completed workout telemetry, interval/lap data, morning physiological recovery metrics (Sleep, HRV, RHR), and run-time environmental weather in a single call.
   - **Multiple sessions that day**: by date, the tool analyses the day's primary run (highest load) and lists any other completed sessions with their ids at the top. If the runner clearly meant a different session, re-call `analyze_workout(workout_id="<id>")`; otherwise briefly acknowledge the other sessions as context.
   - **Classify Workout** (this also selects the output format in step 3):
     - **Easy / Recovery Run**: easy, recovery, aerobic or shakeout runs (strides included).
     - **Long Run**: the title names it a long run, or it lasts ~90 minutes or more, even when fully easy.
     - **Structured Workout**: intervals, tempo, threshold, race, progressive, push, MP block, reps.
     - A **Planned structure & execution** section means the session was built in the TrainingPeaks workout builder: that plan is the source of truth for what was intended. A builder plan alone does not make a run structured: a single steady easy-pace target is still an Easy Run. **Planned session notes** carry the coach's intent for any session.

2. **Perform Differential Physiological Synthesis**:
   - Analyze every session fully, whatever its type; the step 3 format only controls how much of the analysis is reported.
   - **For Easy & Recovery Runs**:
     - Evaluate low-intensity compliance (holding heart rate in Zone 1/2), overall pace/HR stability, and cardiac drift across the duration.
     - Look for 'gray zone' (Zone 3/4) creep where recovery runs are executed too fast, compromising metabolic recovery.
     - Reference lap data if pacing surges or significant cardiac drift are present across splits.
   - **For Structured Workouts (Intervals, Tempo, Threshold, Race, Progressive, MP Blocks, Reps)**:
     - If a **Planned structure & execution** section is present, judge execution **step by step against the planned targets** (the Check column), then use the **Repeated blocks** summary for rep-to-rep pace consistency and HR drift at matched pace. Judge the quality block by its own **Decoupling per work block** value (`[key block]` marks the highest-intensity block), not by the whole session.
     - Otherwise analyze the **Laps Breakdown**: evaluate individual work intervals vs. recovery laps for pacing consistency (even/negative splits vs. fading), heart rate response, recovery lap HR drop, and cadence stability.
     - Long runs with embedded race-pace blocks: evaluate that block's pace discipline and decoupling separately from the easy kilometres.
   - **Elevation & Terrain Impact**:
     - Evaluate total elevation gain/loss (+Xm / -Ym), route gradient, and climbing rate (VAM).
     - Compare **Normalized Graded Pace (NGP)** against raw pace: understand that slower raw pace on uphill segments with steady NGP/HR indicates consistent effort and good pacing discipline rather than fatigue or aerobic decoupling.
     - Assess biomechanical adaptations to grade (cadence adjustments, stride length changes on climbs vs. descents).
   - **Aerobic Decoupling & Weather Context**:
     - Synthesize `Pa:Hr` (pace vs. heart rate drift) contextually with run-time environmental conditions (temperature, feels-like, humidity, wind). Distinguish expected thermoregulatory cardiac drift in high heat/humidity from poor pacing or cardiovascular fatigue in moderate conditions.
     - **Reason about drift; don't apply fixed cut-offs.** The tool excludes the first 5 minutes of every session (and the planned warm-up/cool-down for builder workouts); each value's label states its window and duration. Do not recompute or quote a whole-session value. Weigh the value against:
       - **Session design**: continuous efforts (steady runs, long-run race-pace blocks, alternations without full recovery such as Canova) naturally accumulate HR creep; separate reps with full recovery should show little rep-to-rep drift.
       - **Intensity relative to threshold** (drift grows with intensity), and the **window duration** (short windows are noisier).
       - **Conditions** (heat, humidity, wind, terrain) and **readiness** (sleep, HRV, RHR trend; fueling/hydration if mentioned).
       - Literature reference points (e.g. Friel's ~5% for steady aerobic efforts, ~3.5% in aerobic-threshold tests) can inform the reasoning but are not verdicts.
   - **Physiological Recovery & Readiness Context**:
     - Cross-reference run execution against morning recovery metrics from `analyze_workout` (Sleep duration, HRV baseline stability, and Resting Heart Rate trends) to assess readiness and strain.
   - **Goal Alignment**: Connect the run execution to long-term goal pacing and phase progression.

3. **Deliver Workout Summary**:
   - Deliver an objective, data-backed assessment in clean standard Markdown:
     - Plain-Text Metrics & Progressions: Follow the coach's standard plain-text formatting rules — plain metric names (`Pa:Hr`, `NGP`, `HR 155 bpm`, `4:30/km`) and text arrows (`->` or `→`), never LaTeX.
   - **Pick the format from the step 1 classification.** If the runner explicitly asks for more or less detail, follow that instead.
   - **Structured Workouts & Long Runs → Full format:**
     1. **Session Overview**: Date, sport, title, distance, duration, and environmental conditions.
     2. **🎯 Execution & Physiological Assessment**: Honest, data-backed critique of what was executed well vs. breakdowns (e.g. pacing control, Zone 1/2 discipline, Pa:Hr drift context, terrain management, and recovery state). For structured sessions, summarize interval/lap execution in prose here.
     3. **🚀 Key Takeaways & Adjustments**: Specific, actionable coaching directives for upcoming workouts and recovery.
   - **Easy & Recovery Runs → Concise format** (short and to the point: Execution + Key Takeaways together under ~120 words):
     1. **Session Overview**: four bullets, omitting unavailable items: **Date & Title** (plus other same-day sessions, if any); **Volume** (distance | duration | pace (NGP)); **Physiological Load** (HR avg (max) | cadence | Pa:Hr | rTSS); **Environment** (location | temperature (feels like), humidity, wind, terrain +gain / -loss).
     2. **🎯 Execution**: three one-line bullets, each opening with ✅ (on target), ⚠️ (watch) or ❌ (missed), then the verdict with its key number:
        - **Intensity**: HR zone discipline vs. the plan (pace/HR target, if any). Running slightly slower than the planned pace at a truly easy HR is correct execution: say so in a few words.
        - **Aerobic stability**: Pa:Hr with a few words of context (conditions, terrain).
        - **Readiness**: the morning HRV / RHR / sleep signal (omit if no recovery data).
        - Add a **Mechanics** or **Terrain** bullet only when the data shows something notable (e.g. cadence fade, ground-contact spike, hilly route). Address athlete feedback (RPE/comment) in the relevant bullet.
        - No physiology explanations, and don't restate Session Overview numbers unless they carry the verdict.
     3. **🚀 Key Takeaways**: at most 2 numbered one-line directives about what should change in the coming days. Skip generic reminders (e.g. injury prevention, strength work) unless today's data or athlete feedback points to them.
     - Example of the expected length and tone (illustrative values):
       ```
       ### 🎯 Execution
       * ✅ **Intensity:** HR 131 bpm (76% LTHR), Zone 2 throughout; 6:05/km inside the 5:55–6:15/km plan.
       * ⚠️ **Aerobic stability:** Pa:Hr 6.1%, high for a cool, flat run: likely residual fatigue.
       * ✅ **Readiness:** HRV 48 ms and RHR 51 bpm at baseline; 7.9 h sleep.

       ### 🚀 Key Takeaways
       1. Keep tomorrow's recovery run under HR 135 bpm so the drift can settle.
       2. Re-check Pa:Hr on Thursday's easy run before the long run.
       ```

