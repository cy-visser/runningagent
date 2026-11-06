---
name: trend-analysis
description: Long-horizon (6+ weeks) analysis of the training log - progress, how much weekly running load the runner can handle, pacing (easy pace, workout headroom, training paces), which kinds of training work, and progress toward the goal and north star - condensed into recommendations for the next block (and the north star).
---

# Trend Analysis Skill

Analyse months of training to answer: how the runner has developed, how much weekly running they can handle,
how fast they should run, which kinds of training work for them, and how they are tracking toward their goal
(and north star). The report's charts and tables are rendered automatically from the tool's data; your job is
the reasoning, delivered as a few concrete recommendations.

## Protocol

1.  **Gather Data**: call `fetch_trend_data` (in the same step as `load_skill`). Pass `weeks` only when the
    runner names a period (e.g. "since July" -> the number of weeks since then); otherwise use the default.
    The tool fills in workouts missing from the training log, then returns deterministic evidence: goal
    context (current block, projection, CTL trajectory, north star), progress, volume levels, a load-capacity
    outlook, pacing evidence and training patterns (all computed over the full window), plus the weekly rows
    and raw comments of the last 8 weeks (older comments only when they mention a niggle).
2.  **Analyse** (internally, to ground the recommendations; none of this is written out as sections):
    *   **Goal context**: the projection vs the goal (gap, confidence, stale evidence), CTL vs the goal's
        peak-CTL target and required ramp, weeks to race and whether the block has started. With a north
        star: the north-star equivalent and gap, the north-star peak-CTL range and the sub-goal results
        (the GOAL PLAN table in your instructions).
        Riegel equivalents from short races are optimistic for the marathon: never present them as a promise.
    *   **Progress**: development of fitness (CTL), threshold paces and health (HRV, RHR, sleep) between the
        first and last weeks:
        - **Pace @ LT1** (top of TP zone 2) and **Pace @ LT2** (LTHR), from a rolling 4-week HR->pace fit:
          faster pace at the same HR means the aerobic / lactate threshold moved up. `*` in the weekly rows marks
          an extrapolated value; when the progress table notes an unconfirmed LTHR, LT2 depends on it.
        - **Key-run Pa:Hr %**: heart-rate drift vs pace in the goal-specific key sessions only (label says
          which): tempo/threshold steps for 5K/10K, the long run (or its race-pace blocks) for 10 Mile to
          marathon. Lower is better; under 5% is aerobically stable. Weeks without a key session have no value.
        - Trend verdicts (`🟢 improving` / `🟡 stable` / `🔴 declining`) judge the runner, while the arrow is only
          the direction of the number (a rising Pa:Hr is `↑ 🔴 declining`).
    *   **Load Capacity** (how much): use the volume-levels table and the outlook lines. A level is proven
        only when the table says so. Never claim capacity above the highest week run; higher targets are
        untested. There is no coded ramp limit: when you estimate how long a target takes, derive it from the
        km gap and a weekly ramp you judge appropriate for this runner (CTL, levels held, training age and
        race background such as previous marathon builds, recovery markers) and state the ramp you assumed.
        A weekly-km recommendation follows the "Weekly volume reference" line in the goal context (block
        target and per-week linear path, identical in the schedule audit); the capacity evidence and your
        ramp judgement say whether that path is safe for this runner. Never cite a generic "10% rule".
    *   **Pacing** (how fast): the easy-pace range and easy-run discipline; per workout band, "you can run
        faster" only where the verdict is `room to go faster`, with the suggested s/km. `too hard`, `on target`
        and `insufficient` are taken as they are. Training paces come from the threshold estimate, never from
        the goal time. When the LTHR check is `unconfirmed`, HR-based results rely on an unconfirmed LTHR: a
        30-minute solo time trial (LTHR = average HR of the last 20 minutes) or a 10K race, once recovered from
        any upcoming goal race, comes before changing paces.
    *   **Training Patterns** (what kind): session mix, long-run share and sleep versus the next week's easy-EF
        and HRV response. A group marked INSUFFICIENT is unknown, not a finding. Patterns are associations,
        never causes; an EF difference under 1% is weak.
    *   **Long runs (your judgement)**: there is no computed long-run target. Reason any long-run recommendation
        from the "Long-run history" line in the Load capacity data, the weekly volume path and the time to the
        goal / north-star race: progress from what the runner has actually run, never a jump, and keep the long
        run proportionate to the week. Never quote a generic range or a fixed duration cap.
    *   Use the raw athlete comments only as context (e.g. a niggle explaining a non-tolerated week).

## Output

The web report already shows the goal projection, progress cards, charts (volume & CTL, threshold paces,
fitness vs goal CTL band, implied race time, north-star milestones, long-run & volume readiness), the load-capacity
ladder and the training paces table. **Do not write an overview, tables, or Progress / Load Capacity / Pacing /
Training Patterns sections, and do not restate the charts.** Write only:

1. `### 🎯 Next Block: Top 3`: exactly three numbered recommendations for the next training block (the current
   block, or the upcoming one when it has not started). Each is:
   - a **bold, concrete action** (weekly km, long-run km, paces in min/km, session mix or a test), then
   - one line starting `Why:` that names the evidence it rests on, quoting the tool's numbers exactly
     (e.g. proven level and the km gap, a pacing verdict, a progress trend, the projection gap).
   Rank them by expected impact on the goal. No generic advice; each must follow from this runner's data.
2. `### 🧭 North Star` (only for a goal plan, i.e. GOAL PLAN in your instructions): one to three numbered
   recommendations, same format, on what the coming block must protect or build for the north star (aerobic
   base vs the north-star peak-CTL range, a long-run progression reasoned from the history, weekly volume vs the block target
   on the way to the north-star peak weekly km). Quote the north-star equivalent and gap exactly once.

Clean standard Markdown, plain-text metrics, text arrows (`->` or `→`), never LaTeX. Quote every number
exactly as the tool provides it; never recompute or invent values. If the coverage line reports workouts that
could not be recorded, end with one italic sentence saying the trend is incomplete for those weeks and that
asking again later fills them in.
