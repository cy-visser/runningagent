---
name: trend-analysis
description: Long-horizon (6+ weeks) analysis of the training log - progress, how much weekly running load the runner can handle, pacing (easy pace, workout headroom, training paces) and which kinds of training work.
---

# Trend Analysis Skill

Analyse months of training to answer four questions, one per section: how the runner has developed, how much
weekly running they can handle, how fast they should run, and which kinds of training work for them.

## Protocol

1.  **Gather Data**: call `fetch_trend_data` (in the same step as `load_skill`). Pass `weeks` only when the
    runner names a period (e.g. "since July" -> the number of weeks since then); otherwise use the default.
    The tool fills in workouts missing from the training log, then returns deterministic tables and evidence:
    progress, weekly rows, volume levels, a load-capacity outlook, pacing evidence, training patterns and the
    runner's raw comments.
2.  **Analyse**, keeping each finding in exactly one section:
    *   **Progress**: development of fitness (CTL), threshold paces and health (HRV, RHR, sleep) between the
        first and last weeks:
        - **Pace @ LT1** (top of TP zone 2) and **Pace @ LT2** (LTHR), from a rolling 4-week HR->pace fit:
          faster pace at the same HR means the aerobic / lactate threshold moved up. `*` in the weekly rows marks
          an extrapolated value; when the progress table notes an unconfirmed LTHR, say LT2 depends on it.
        - **Key-run Pa:Hr %**: heart-rate drift vs pace in the goal-specific key sessions only (label says
          which): tempo/threshold steps for 5K/10K, the long run (or its race-pace blocks) for 10 Mile to
          marathon. Lower is better; under 5% is aerobically stable. Weeks without a key session have no value.
        - Quote each Trend verdict (`🟢 improving` / `🟡 stable` / `🔴 declining`) exactly as given: it judges
          the runner, while the arrow is only the direction of the number (a rising Pa:Hr is `↑ 🔴 declining`).
    *   **Load Capacity** (how much): use the volume-levels table and the outlook lines. A level is proven
        only when the table says so. Answer each target (50 / 60 / 70 / 80 / 100 km) with its status and build
        weeks exactly as given. Never claim capacity above the highest week run; describe higher targets as
        untested.
    *   **Pacing** (how fast): the easy-pace range (TP heart-rate zone 2 through the runner's HR->pace model)
        and easy-run discipline; per workout band, say "you can run faster" only where the verdict is `room to
        go faster`, quoting the evidence (sessions, pace hit rate, %LTHR, decoupling, suggested s/km). Report
        `too hard`, `on target` and `insufficient` as they are. Compare the observed threshold with the TP
        setting. Training paces come from the threshold estimate, never from the goal time.
        Report the LTHR check line. When it is `unconfirmed`, say that the HR-based results (easy-pace zone,
        `room to go faster`) rely on an LTHR the data has not confirmed, and recommend a 30-minute solo time trial
        (LTHR = average HR of the last 20 minutes) or a 10K race once recovered from any upcoming goal race,
        before changing paces.
    *   **Training Patterns** (what kind): session mix, long-run share and sleep versus the next week's easy-EF
        and HRV response. Every claim cites n and the effect size; a group marked INSUFFICIENT is unknown, not a
        finding. Patterns are associations, never causes: never write "the data demonstrates", "benefits from"
        or similar; an EF difference under 1% is weak. Do not repeat volume or pace findings here.
    *   **Long runs**: any long-run recommendation (distance per week, in Load Capacity or the actions) uses only
        the "Long-run target" line in the Load capacity data, quoted exactly; never derive a distance from the
        pattern split or from general norms.
    *   Use the raw athlete comments only as context (e.g. a niggle explaining a non-tolerated week).

## Output

Clean standard Markdown, plain-text metrics, text arrows (`->` or `→`), never LaTeX. Quote every number
exactly as the tool provides it; never recompute or invent values.

1. **Overview**: the window, number of workouts and data coverage in two or three sentences. If the coverage
   line reports workouts that could not be recorded, say the trend is incomplete for the marked weeks and that
   asking again later fills them in.
2. **📊 Trend Metrics**: write the line `[[TREND_METRICS]]` exactly once, on its own line. It is replaced
   automatically with the Progress, Weekly volume levels, Training paces and Workout calibration tables.
   **Do not re-type these tables.**
3. **📈 Progress**
4. **🏋️ Load Capacity**
5. **🏃 Pacing**
6. **🧩 Training Patterns**
7. **🎯 Top 3 Actions for the Next Block**: at most three numbered, concrete actions (paces, weekly km,
   session mix), each traced to a finding above. No generic advice.
