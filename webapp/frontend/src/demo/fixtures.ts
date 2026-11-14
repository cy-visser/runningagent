import type {
  AuditReportData,
  CheckinReportData,
  MeResponse,
  PlanRowAction,
  PlanSessionRow,
  PlanWeek,
  ProfileResponse,
  StagedTrainingPlan,
  TrendReportData,
  TrendWeekPoint,
  WorkoutReportData,
} from "../shared/types";

export const DEMO_ME_READY: MeResponse = {
  email: "cyrille@cyvisser.altostrat.com",
  runner_id: "cyrille_visser",
  display_name: "Cyrille Visser",
  initials: "CV",
  profile_state: "ready",
  tp: {
    connected: true,
    tp_athlete_id: "4819204",
    tp_name: "Cyrille Visser",
    updated_at: "2026-11-05T08:30:00Z",
  },
  summary: {
    firstname: "Cyrille",
    lastname: "Visser",
    full_name: "Cyrille Visser",
    location: "Amsterdam, Netherlands",
    goal_type: "plan",
    active_goal: "Sub-1:26 Half Marathon",
    active_race_name: "CPC Loop Den Haag",
    active_date: "2027-03-14",
    weeks_remaining: 18.4,
    north_star: {
      goal: "Sub-2:58 Marathon",
      race_name: "Rotterdam Marathon",
      race_date: "2027-04-11",
    },
  },
};

export const DEMO_ME_ONBOARDING: MeResponse = {
  email: "new.runner@cyvisser.altostrat.com",
  runner_id: null,
  display_name: "Alex Vermeer",
  initials: "AV",
  profile_state: "none",
  tp: {
    connected: false,
    tp_athlete_id: null,
    tp_name: null,
    updated_at: null,
  },
  summary: null,
};

export const DEMO_PROFILE_RESPONSE: ProfileResponse = {
  runner_id: "cyrille_visser",
  profile_state: "ready",
  tp: DEMO_ME_READY.tp,
  summary: DEMO_ME_READY.summary,
  profile: {
    firstname: "Cyrille",
    lastname: "Visser",
    email: "cyrille@cyvisser.altostrat.com",
    age: "38",
    height: "183 cm",
    weight: "73.5 kg",
    location: "Amsterdam, Netherlands",
    goal_type: "plan",
    goal_set_date: "2026-09-15",
    north_star: {
      goal: "Sub-2:58 Marathon",
      race_name: "NN Marathon Rotterdam",
      start_date: "2027-01-04",
      race_date: "2027-04-11",
      taper_weeks: 3,
    },
    sub_goals: [
      {
        goal: "Sub-39:30 10K",
        race_name: "Zevenheuvelenloop Warm-Up 10K",
        start_date: "2026-09-15",
        race_date: "2026-10-18",
        taper_weeks: 1,
        result: "39:12 (chip) — strong negative split",
      },
      {
        goal: "Sub-1:26 Half Marathon",
        race_name: "CPC Loop Den Haag",
        start_date: "2026-10-26",
        race_date: "2027-03-14",
        taper_weeks: 1.5,
        result: null,
      },
    ],
    personal_records: {
      "5k": { time: "18:41", time_s: 1121, date: "2026-06-14" },
      "10k": { time: "39:12", time_s: 2352, date: "2026-10-04" },
      "10_mile": null,
      half_marathon: { time: "1:27:48", time_s: 5268, date: "2026-03-22" },
      marathon: { time: "3:04:19", time_s: 11059, date: "2025-10-19" },
    },
    injuries: "Mild left Achilles tightness after steep hill repeats; managed with eccentric heel drops.",
    run_time_of_day: "morning",
    strength_time_of_day: "evening",
    shoe_rotation: {
      easy: "Superblast 2",
      tempo: "Magic Speed 4",
      interval: "Magic Speed 4",
      long_run: "Superblast 2",
      race: "Metaspeed Sky Paris",
    },
  },
};

export const DEMO_CHECKIN_DATA: CheckinReportData = {
  version: 1,
  window: { start: "2026-10-22", end: "2026-11-05" },
  ctl: {
    current: 61.4,
    target: 74.0,
    range: [68, 78],
    pct: 83,
    weeks_remaining: 18.4,
    required_ramp: 0.78,
    ramp_tier: "safe",
    phase: "build",
    pre_taper_ctl: null,
    atl: 66.2,
    tsb: -4.8,
  },
  pmc: [
    { date: "2026-08-14", ctl: 47.2, atl: 50.1, tsb: -2.9 },
    { date: "2026-08-28", ctl: 49.6, atl: 53.4, tsb: -3.8 },
    { date: "2026-09-11", ctl: 52.1, atl: 56.0, tsb: -3.9 },
    { date: "2026-09-25", ctl: 54.8, atl: 59.2, tsb: -4.4 },
    { date: "2026-10-09", ctl: 57.3, atl: 54.1, tsb: 3.2 },
    { date: "2026-10-18", ctl: 56.9, atl: 61.8, tsb: -4.9 },
    { date: "2026-10-25", ctl: 59.1, atl: 63.7, tsb: -4.6 },
    { date: "2026-11-01", ctl: 60.6, atl: 65.0, tsb: -4.4 },
    { date: "2026-11-05", ctl: 61.4, atl: 66.2, tsb: -4.8 },
  ],
  projection: {
    goal_label: "Sub-1:26 Half Marathon",
    today_s: 5218,
    race_day_s: 5124,
    goal_s: 5160,
    gap_s: -36,
    range_s: [5085, 5168],
    confidence: "High",
    stale: false,
    readiness: "on_track",
    drivers: [
      { driver: "Threshold anchor", evidence: "3 × 3 km @ 3:58/km (24 Oct), LTHR 168 confirmed", implied: "4:03/km (×1.02)" },
      { driver: "Goal-pace work", evidence: "2 × 5 km @ 4:04/km at 91% LTHR (18 Oct)", implied: "4:03/km" },
      { driver: "Durability", evidence: "Longest 24 km, long-run Pa:Hr 3.1% -> strong", implied: "ratio 1.0" },
      { driver: "Load", evidence: "CTL 61 → ~74 race day, TSB -5", implied: "race-day -1.8%" },
      { driver: "Health", evidence: "HRV +4% vs 28d, RHR -1 bpm", implied: "🟢 readiness" },
    ],
  },
  weeks: [
    {
      week: "2026-10-12",
      date_range: "Oct 12 – Oct 18",
      km: 62.4,
      tss: 392,
      easy: 4,
      quality: 1,
      growth_pct: -8.2,
      partial: false,
    },
    {
      week: "2026-10-19",
      date_range: "Oct 19 – Oct 25",
      km: 69.8,
      tss: 446,
      easy: 4,
      quality: 2,
      growth_pct: 11.9,
      partial: false,
    },
    {
      week: "2026-10-26",
      date_range: "Oct 26 – Nov 1",
      km: 73.5,
      tss: 472,
      easy: 4,
      quality: 2,
      growth_pct: 5.3,
      partial: false,
    },
    {
      week: "2026-11-02",
      date_range: "Nov 2 – Nov 5",
      km: 41.2,
      tss: 258,
      easy: 2,
      quality: 1,
      growth_pct: null,
      partial: true,
      in_progress: true,
    },
  ],
  recovery: {
    sleep_avg_h: 7.65,
    hrv_latest: 68.0,
    rhr_latest: 46.0,
    series: [
      { date: "2026-10-26", hrv: 65, rhr: 47, sleep_h: 7.4 },
      { date: "2026-10-29", hrv: 67, rhr: 46, sleep_h: 7.8 },
      { date: "2026-11-01", hrv: 66, rhr: 47, sleep_h: 7.5 },
      { date: "2026-11-05", hrv: 68, rhr: 46, sleep_h: 7.9 },
    ],
  },
  lt: {
    lt1_pace_s: 300,
    lt2_pace_s: 248,
    lt1_prev_s: 306,
    lt2_prev_s: 253,
    lt1_hr: 141,
    lthr: 168,
    lt1_extrapolated: false,
    lt2_extrapolated: false,
  },
};

export const DEMO_CHECKIN_MARKDOWN = `### 🎯 Goal Trajectory Status

**On Track** — Chronic Training Load has climbed to **61.4 CTL**, requiring only **+0.78 CTL/wk** over the next 18.4 weeks, well inside the safe ramp. The projected **1:25:24** leaves a 36 s buffer at target CTL.

### 🔍 Training Load & Adaptation Analysis

- **Intensity & Load:** 80/20 split held at **4 easy / 2 quality** (**73.5 km**, TSB **-4.8**) with easy runs cleanly below LT1 (141 bpm).
- **Recovery & Tendon Watch:** HRV (**68 ms** ↑) and RHR (**46 bpm** →) confirm absorption; keep Friday strides on flat tarmac while on eccentric calf work.

### 🚀 Top 2 Priorities for the Upcoming Week
1. **Hold Sunday's progressive long run at 22 km** with the final 5 km at 4:08–4:12/km (marathon-to-HM bridge effort).
2. **Protect recovery ceiling:** keep easy days below 141 bpm so HRV stays at or above 66 ms.`;

// Implied finish times from weekly LT2 pace (same math as the backend): km * pace / threshold->race ratio.
const HM_FACTOR = 21.0975 / 0.97;
const MARATHON_FACTOR = 42.195 / 0.91;
function withImplied(weeks: TrendWeekPoint[]): TrendWeekPoint[] {
  return weeks.map((w) => ({
    ...w,
    implied_goal_s: w.lt2_pace_s ? Math.round(w.lt2_pace_s * HM_FACTOR) : null,
    implied_ns_s: w.lt2_pace_s ? Math.round(w.lt2_pace_s * MARATHON_FACTOR) : null,
  }));
}

// Required-ramp CTL path for the demo half-marathon block: 61.4 -> 65 at +0.3/wk.
const DEMO_CTL_PLAN = Array.from({ length: 13 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 9, 26 + 7 * i));
  return { week: d.toISOString().slice(0, 10), ctl: Math.min(65, Math.round((61.4 + 0.3 * i) * 10) / 10) };
});

export const DEMO_TREND_DATA: TrendReportData = {
  version: 1,
  window: { start: "2026-05-11", end: "2026-11-05" },
  weeks: withImplied([
    { week: "2026-05-18", complete: true, km: 48.0, tss: 305, runs: 5, quality: 1, long_km: 16, ctl: 43.2, tsb: 1.4, hrv: 61, rhr: 49, sleep_h: 7.3, lt1_pace_s: 318, lt2_pace_s: 262, key_decoupling: 5.4 },
    { week: "2026-06-01", complete: true, km: 52.5, tss: 332, runs: 5, quality: 2, long_km: 18, ctl: 45.1, tsb: -1.8, hrv: 62, rhr: 48, sleep_h: 7.4, lt1_pace_s: 316, lt2_pace_s: 261, key_decoupling: 4.9 },
    { week: "2026-06-15", complete: true, km: 56.2, tss: 355, runs: 5, quality: 2, long_km: 19, ctl: 47.0, tsb: -2.4, hrv: 63, rhr: 48, sleep_h: 7.5, lt1_pace_s: 314, lt2_pace_s: 259, key_decoupling: 4.5 },
    { week: "2026-06-29", complete: true, km: 46.0, tss: 284, runs: 5, quality: 1, long_km: 16, ctl: 46.4, tsb: 5.1, hrv: 65, rhr: 47, sleep_h: 7.7, lt1_pace_s: 313, lt2_pace_s: 258, key_decoupling: 3.9 },
    { week: "2026-07-13", complete: true, km: 59.4, tss: 378, runs: 6, quality: 2, long_km: 20, ctl: 48.9, tsb: -3.2, hrv: 63, rhr: 48, sleep_h: 7.4, lt1_pace_s: 312, lt2_pace_s: 257, key_decoupling: 4.1 },
    { week: "2026-07-27", complete: true, km: 62.8, tss: 398, runs: 6, quality: 2, long_km: 21, ctl: 50.8, tsb: -3.7, hrv: 64, rhr: 47, sleep_h: 7.5, lt1_pace_s: 311, lt2_pace_s: 256, key_decoupling: 3.8 },
    { week: "2026-08-10", complete: true, km: 64.5, tss: 410, runs: 6, quality: 2, long_km: 22, ctl: 52.4, tsb: -3.5, hrv: 64, rhr: 47, sleep_h: 7.6, lt1_pace_s: 309, lt2_pace_s: 255, key_decoupling: 3.6 },
    { week: "2026-08-24", complete: true, km: 53.0, tss: 330, runs: 5, quality: 1, long_km: 18, ctl: 51.9, tsb: 4.6, hrv: 66, rhr: 46, sleep_h: 7.8, lt1_pace_s: 307, lt2_pace_s: 254, key_decoupling: 3.3 },
    { week: "2026-09-07", complete: true, km: 66.8, tss: 428, runs: 6, quality: 2, long_km: 22, ctl: 54.6, tsb: -4.0, hrv: 65, rhr: 47, sleep_h: 7.5, lt1_pace_s: 306, lt2_pace_s: 253, key_decoupling: 3.2 },
    { week: "2026-09-21", complete: true, km: 70.4, tss: 452, runs: 6, quality: 2, long_km: 23, ctl: 57.1, tsb: -4.5, hrv: 66, rhr: 46, sleep_h: 7.6, lt1_pace_s: 304, lt2_pace_s: 252, key_decoupling: 3.0 },
    { week: "2026-10-05", complete: true, km: 68.2, tss: 438, runs: 6, quality: 2, long_km: 22, ctl: 58.0, tsb: -2.1, hrv: 67, rhr: 46, sleep_h: 7.7, lt1_pace_s: 304, lt2_pace_s: 251, key_decoupling: 2.8 },
    { week: "2026-10-19", complete: true, km: 69.8, tss: 446, runs: 6, quality: 2, long_km: 23, ctl: 59.4, tsb: -4.3, hrv: 67, rhr: 46, sleep_h: 7.6, lt1_pace_s: 302, lt2_pace_s: 249, key_decoupling: 2.7 },
    { week: "2026-10-26", complete: true, km: 73.5, tss: 472, runs: 6, quality: 2, long_km: 24, ctl: 61.4, tsb: -4.8, hrv: 68, rhr: 46, sleep_h: 7.8, lt1_pace_s: 300, lt2_pace_s: 248, key_decoupling: 2.5 },
  ]),
  progress: [
    {
      label: "Chronic Load (CTL)",
      first: "43.2",
      latest: "61.4",
      best: "61.4",
      change: "+42%",
      arrow: "↑",
      verdict: "🟢 Improving",
    },
    {
      label: "Pace @ LT1 (top of zone 2)",
      first: "5:17/km",
      latest: "5:02/km",
      best: "5:00/km (wk 2026-10-26)",
      change: "-15 s/km",
      arrow: "↓",
      verdict: "🟢 improving",
    },
    {
      label: "Pace @ LT2 (LTHR)",
      first: "4:21/km",
      latest: "4:10/km",
      best: "4:08/km (wk 2026-10-26)",
      change: "-11 s/km",
      arrow: "↓",
      verdict: "🟢 improving",
    },
    {
      label: "Key-run Pa:Hr % (long run / race-pace blocks)",
      first: "4.9",
      latest: "2.8",
      best: "2.5 (wk 2026-10-26)",
      change: "-2.1",
      arrow: "↓",
      verdict: "🟢 improving",
    },
    {
      label: "Overnight HRV",
      first: "61 ms",
      latest: "68 ms",
      best: "68 ms",
      change: "+11%",
      arrow: "↑",
      verdict: "🟢 Absorbing",
    },
  ],
  levels: [
    { level: 50, weeks: 7, streak: 4, tolerated_share: 1.0, hrv_delta_pct: 2.1, rhr_delta: -1.0, rpe: 4.8, proven: true },
    { level: 60, weeks: 9, streak: 5, tolerated_share: 0.89, hrv_delta_pct: 1.4, rhr_delta: -0.5, rpe: 5.3, proven: true },
    { level: 70, weeks: 4, streak: 3, tolerated_share: 0.75, hrv_delta_pct: 0.8, rhr_delta: 0.0, rpe: 5.8, proven: true },
    { level: 80, weeks: 0, streak: 0, tolerated_share: 0.0, hrv_delta_pct: null, rhr_delta: null, rpe: null, proven: false },
  ],
  outlook: {
    proven_km: 70,
    max_km: 73.5,
    current_km: 73.5,
    targets: [
      { target: 50, status: "proven", gap_km: 0 },
      { target: 60, status: "proven", gap_km: 0 },
      { target: 70, status: "proven", gap_km: 0 },
      { target: 80, status: "within reach", gap_km: 6.5 },
      { target: 100, status: "untested", gap_km: 26.5 },
    ],
  },
  key_run_label: "long run / race-pace blocks",
  goal: {
    training_goal: "Sub-1:26 Half Marathon",
    label: "Half Marathon",
    kind: "sub_goal",
    race_date: "2027-03-14",
    weeks_to_race: 18.4,
    before_start: false,
    goal_s: 5160,
    projection: {
      today_s: 5262,
      race_day_s: 5225,
      goal_s: 5160,
      gap_s: 65,
      range_s: [5170, 5340],
      confidence: "Medium",
      stale: false,
    },
    ctl: {
      current: 61.4,
      target_peak: 65,
      range: [58, 70],
      required_ramp: 0.3,
      phase: "build",
      plan: DEMO_CTL_PLAN,
    },
  },
  north_star: {
    training_goal: "Sub-2:58 Marathon",
    label: "Marathon",
    race_name: "NN Marathon Rotterdam",
    race_date: "2027-04-11",
    weeks_to_race: 22.4,
    target_s: 10680,
    equivalent_s: 10893,
    gap_s: 213,
    ctl_range: [70, 85],
    milestones: [
      { training_goal: "Sub-39:30 10K", race_date: "2026-10-18", status: "done", target_equiv_s: 10902, result_equiv_s: 10819 },
      { training_goal: "Sub-1:26 Half Marathon", race_date: "2027-03-14", status: "active", target_equiv_s: 10758, result_equiv_s: null },
    ],
  },
  paces: [
    { name: "Easy (Z2 128-145 bpm)", pace: "4:55–5:30/km" },
    { name: "Marathon", pace: "4:32/km" },
    { name: "Threshold", pace: "4:08/km" },
    { name: "VO2max", pace: "3:52/km" },
  ],
};

export const DEMO_TREND_MARKDOWN = `### 🎯 Next Block: Top 3
1. **Progress steady build weeks from 73 to 80–85 km/wk (+2–3 km/wk with a down week every 4th week).**
   Why: 70+ km/wk held 3 consecutive weeks (4 weeks total) with HRV (+0.8%) and RHR (0.0 bpm) steady; 80 km/wk is +6.5 km/wk above current.
2. **Step the long run from 24 to 26 km over the next 3 weeks and put 2×5 km at 4:05/km inside it every 10 days.**
   Why: The last 4 long runs were 22–24 km at ~32% of weekly volume, supporting gradual progression while closing the +1:05 HM projection gap.
3. **Run threshold reps at 4:05/km instead of 4:08/km.**
   Why: The last threshold sessions hit the 4:08/km target on 100% of reps at 89% of LTHR with 2.5% Pa:Hr, so there is about 3 s/km of headroom.

### 🧭 North Star
1. **Keep one 26–28 km easy long run every third week from January.**
   Why: Current projection's north-star equivalent 3:01:33 (gap +3:33 slower) requires building aerobic durability beyond HM race distance.
2. **Arrive at the north-star block start (2027-01-04) with CTL ≥ 65.**
   Why: North-star peak-CTL range 70–85 leaves 14 weeks of build from there.`;

export const DEMO_AUDIT_DATA: AuditReportData = {
  version: 1,
  window: { start: "2026-10-26", end: "2026-11-29" },
  weeks: [
    {
      week: "2026-10-26",
      date_range: "Oct 26 – Nov 1, 2026",
      km: 73.5,
      tss: 472,
      easy: 4,
      quality: 2,
      bike: 1,
      strength: 1,
      long_run: "Long run: 24 km (1:52, 33% of the week's running km) | 14 wk to Marathon",
      vs_prior_pct: 5.0,
      notes: [],
      sessions: [
        { date: "2026-10-26", sport: "Strength", title: "Lower-body & Achilles Eccentrics", category: "strength", km: 0, minutes: 40, tss: 25, completed: true },
        { date: "2026-10-27", sport: "Run", title: "12 km w/ 6×1 km @ 3:46/km", category: "quality", km: 12.0, minutes: 56, tss: 88, completed: true },
        { date: "2026-10-28", sport: "Run", title: "Easy Aerobic 10 km", category: "easy", km: 10.0, minutes: 50, tss: 52, completed: true },
        { date: "2026-10-29", sport: "Run", title: "14 km Threshold Cruise (2×20m)", category: "quality", km: 14.0, minutes: 64, tss: 98, completed: true },
        { date: "2026-10-30", sport: "Bike", title: "Z1 Recovery Spin", category: "bike", km: 0, minutes: 45, tss: 30, completed: true },
        { date: "2026-10-31", sport: "Run", title: "Easy 13.5 km + 6×20s strides", category: "easy", km: 13.5, minutes: 66, tss: 69, completed: true },
        { date: "2026-11-01", sport: "Run", title: "Progressive Long Run 24 km", category: "easy", km: 24.0, minutes: 112, tss: 110, completed: true },
      ],
    },
    {
      week: "2026-11-02",
      date_range: "Nov 2 – Nov 8, 2026",
      km: 71.5,
      tss: 458,
      easy: 3,
      quality: 2,
      bike: 1,
      strength: 1,
      long_run: "Long run: 22 km (1:43, 30% of the week's running km) | 13 wk to Marathon",
      vs_prior_pct: -2.7,
      notes: ["Nov 06: Keep Friday strides strictly on flat tarmac"],
      sessions: [
        { date: "2026-11-03", sport: "Run", title: "12 km w/ 5×1 km @ 3:48/km", category: "quality", km: 12.0, minutes: 55, tss: 86, completed: true },
        { date: "2026-11-04", sport: "Run", title: "Easy Recovery 11.5 km", category: "easy", km: 11.5, minutes: 58, tss: 58, completed: true },
        { date: "2026-11-05", sport: "Run", title: "14 km Tempo Cruise (2×20 min @ 4:02/km)", category: "quality", km: 14.0, minutes: 63, tss: 96, completed: true },
        { date: "2026-11-06", sport: "Strength", title: "Heavy Calf + Single-leg RDL", category: "strength", km: 0, minutes: 35, tss: 22, completed: false },
        { date: "2026-11-07", sport: "Run", title: "12 km Easy + 6×20s tarmac strides", category: "easy", km: 12.0, minutes: 59, tss: 62, completed: false },
        { date: "2026-11-07", sport: "Bike", title: "Easy Spin 40 min", category: "bike", km: 0, minutes: 40, tss: 26, completed: false },
        { date: "2026-11-08", sport: "Run", title: "22 km Progressive Long Run", category: "easy", km: 22.0, minutes: 103, tss: 108, completed: false },
      ],
    },
    {
      week: "2026-11-09",
      date_range: "Nov 9 – Nov 15, 2026",
      km: 76.0,
      tss: 488,
      easy: 3,
      quality: 2,
      bike: 1,
      strength: 1,
      long_run: "Long run: 24 km (1:52, 32% of the week's running km) | 12 wk to Marathon",
      vs_prior_pct: 6.3,
      notes: [],
      sessions: [
        { date: "2026-11-09", sport: "Strength", title: "Strength & Soleus Load", category: "strength", km: 0, minutes: 40, tss: 24, completed: false },
        { date: "2026-11-10", sport: "Run", title: "13 km w/ 4×2 km @ 3:56/km", category: "quality", km: 13.0, minutes: 60, tss: 92, completed: false },
        { date: "2026-11-11", sport: "Run", title: "Easy Aerobic 12 km", category: "easy", km: 12.0, minutes: 60, tss: 60, completed: false },
        { date: "2026-11-12", sport: "Run", title: "15 km HM-Pace Alternations", category: "quality", km: 15.0, minutes: 68, tss: 104, completed: false },
        { date: "2026-11-13", sport: "Bike", title: "Z1 Flush Ride", category: "bike", km: 0, minutes: 45, tss: 28, completed: false },
        { date: "2026-11-14", sport: "Run", title: "Easy 12 km", category: "easy", km: 12.0, minutes: 60, tss: 60, completed: false },
        { date: "2026-11-15", sport: "Run", title: "Long Run 24 km", category: "easy", km: 24.0, minutes: 112, tss: 120, completed: false },
      ],
    },
    {
      week: "2026-11-16",
      date_range: "Nov 16 – Nov 22, 2026",
      km: 58.0,
      tss: 360,
      easy: 3,
      quality: 1,
      bike: 1,
      strength: 1,
      long_run: "Long run: 18 km (1:24, 30% of the week's running km) | 11 wk to Marathon",
      vs_prior_pct: -23.7,
      notes: ["Nov 18: Lisbon work trip (warm, hilly)"],
      sessions: [
        { date: "2026-11-17", sport: "Run", title: "11 km w/ 6×3 min @ LT2", category: "quality", km: 11.0, minutes: 52, tss: 78, completed: false },
        { date: "2026-11-18", sport: "Run", title: "Easy Tagus Riverfront 10 km", category: "easy", km: 10.0, minutes: 50, tss: 50, completed: false },
        { date: "2026-11-19", sport: "Strength", title: "Hotel Mobility & Calf Isometrics", category: "strength", km: 0, minutes: 30, tss: 18, completed: false },
        { date: "2026-11-20", sport: "Run", title: "Easy 11 km", category: "easy", km: 11.0, minutes: 55, tss: 55, completed: false },
        { date: "2026-11-21", sport: "Bike", title: "Recovery Spin", category: "bike", km: 0, minutes: 40, tss: 25, completed: false },
        { date: "2026-11-22", sport: "Run", title: "Cutback Long Run 18 km", category: "easy", km: 18.0, minutes: 86, tss: 92, completed: false },
      ],
    },
  ],
};

export const DEMO_AUDIT_MARKDOWN = `### Assessment

- **Polarisation & Spacing:** Build weeks hold a clean **2 quality / 3–4 easy** split with >= 48 h between Tuesday reps and Thursday threshold.
- **Progression & Cutback:** Volume steps **+6%** into Nov 9–15 (**76.0 km**) before a well-timed **-24% cutback** (**58.0 km**) during the Lisbon trip.
- ⚠️ **Travel & Achilles Watch (Nov 16–22):** Lisbon hills increase left Achilles load alongside Tuesday LT2 work.

### Recommendations

- **Sub goal (Sub-1:26 HM):**
  - Cap Nov 12's 15 km HM-pace alternations at LTHR (**168 bpm**) rather than forcing pace in wind.
  - Keep the Nov 18 Lisbon easy run on the flat Tagus riverfront path.
- **North star (Sub-2:58 Marathon):**
  - Extend Nov 15's long run from **24 km -> 26 km** (easy Z2) before the Nov 22 Lisbon cutback to keep marathon durability progressing.`;


/** Rolling 14.2 km elevation profile for the workout banner demo. */
const DEMO_ELEVATION: Array<[number, number]> = Array.from({ length: 60 }, (_, i) => {
  const km = +(((i + 0.5) * 14.2) / 60).toFixed(2);
  const alt = 6 + 14 * Math.sin(i / 6) ** 2 + 9 * Math.sin(i / 2.7) ** 2;
  return [km, +alt.toFixed(1)];
});

export const DEMO_WORKOUT_DATA: WorkoutReportData = {
  version: 1,
  workout_id: "3681731939",
  title: "Tempo 3x10' @ Threshold",
  sport: "Run",
  sport_family: "run",
  date: "2026-11-04",
  start_time: "07:12",
  location: "Amsterdam",
  structured: true,
  tiles: [
    { key: "distance", label: "Distance", value: "14.2", unit: "km" },
    { key: "duration", label: "Duration", value: "1:08:34" },
    { key: "pace", label: "NGP", value: "4:49", unit: "/km" },
    { key: "hr", label: "Avg HR", value: "152", unit: "bpm", sub: "max 176" },
    { key: "tss", label: "rTSS", value: "92" },
    { key: "decoupling", label: "Pa:Hr", value: "3.1", unit: "%" },
  ],
  elevation: { gain_m: 86, loss_m: 84, profile: DEMO_ELEVATION },
  hr_zones: [
    { label: "Z1", name: "Zone 1", pct: 8.2, seconds: 337 },
    { label: "Z2", name: "Zone 2", pct: 41.0, seconds: 1687 },
    { label: "Z3", name: "Zone 3", pct: 13.9, seconds: 572 },
    { label: "Z4", name: "Zone 4", pct: 33.1, seconds: 1362 },
    { label: "Z5", name: "Zone 5", pct: 3.8, seconds: 156 },
  ],
  weather: { temp_c: 11, feels_like_c: 9, humidity: 78, wind_kmh: 14 },
  readiness: [
    { key: "hrv", label: "HRV", value: 52, unit: "ms", date: "2026-11-04", direction: "up", tone: "emerald" },
    { key: "rhr", label: "RHR", value: 49, unit: "bpm", date: "2026-11-04", direction: "flat", tone: "slate" },
    { key: "sleep", label: "Sleep", value: 7.6, unit: "h", date: "2026-11-04", direction: null, tone: "slate" },
  ],
  other_sessions: [],
};

export const DEMO_WORKOUT_MARKDOWN = `## Tempo 3x10' @ Threshold

### Session Overview
* **Date & Title:** Wed 4 Nov 2026, Tempo 3x10' @ Threshold
* **Volume:** 14.2 km | 1:08:34 | 4:49/km (NGP)
* **Physiological Load:** HR 152 bpm (max 176) | 178 spm | Pa:Hr 3.1% | rTSS 92
* **Environment:** Amsterdam | 11°C (feels 9°C), 78%, 14 km/h | +86 m / -84 m

---

### 🎯 Execution & Physiological Assessment

#### Pacing & Quality Execution
* **Threshold blocks:** All three 10' reps landed cleanly at **4:12, 4:14, and 4:15/km** (3 s/km spread, 3/3 inside the 4:10–4:20/km target) with crisp 178 spm cadence over +86 m rolling park terrain.
* **Rep HR progression:** Work-bout HR climbed steadily from **164 → 167 → 169 bpm**, capping just below your 170 bpm LTHR without spilling into Zone 5 until a brief final-minute crest.
* ⚠️ **Recoveries:** Between-rep HR only dropped to **148 bpm** during the 2' floats (~5:35/km), narrowing cardiac recovery margin before rep 3.

#### Heart Rate Dynamics & Aerobic Stability
* **Aerobic stability & readiness:** Windowed **Pa:Hr of 3.1%** in cool 11°C (14 km/h wind) conditions alongside rising morning HRV (**52 ms** ↑, 7.6 h sleep) confirms strong lactate clearance for **Sub-1:26 HM** while preserving **Sub-2:58 Marathon** base durability.

---

### 🚀 Key Takeaways & Adjustments
1. **Sub goal (Sub-1:26 HM):** Progress to **3x12' @ 4:10–4:18/km** next week, slowing the 2' float recoveries to **5:55–6:10/km** so HR drops below 140 bpm between reps.
2. **North star (Sub-2:58 Marathon):** Keep Saturday's 24 km long run strictly Zone 2 (< 141 bpm) on flat tarmac to protect left Achilles recovery after today's 92 rTSS load.`;

/** "2026-11-23" + n days (UTC, so the demo is timezone-independent). */
function demoAddDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

const DEMO_PLAN_START = "2026-11-23";
const DEMO_PLAN_WEEKS = 16;

function demoPhase(week: number): string {
  if (week <= 5) return "base";
  if (week <= 11) return "build";
  if (week <= 14) return "peak";
  return "taper";
}

/** One week of the demo plan: run sessions + 2x strength (1x in peak/taper) + an easy spin. */
function demoPlanWeek(week: number): PlanWeek {
  const start = demoAddDays(DEMO_PLAN_START, (week - 1) * 7);
  const phase = demoPhase(week);
  const down = week % 4 === 0;
  const scale = down ? 0.75 : 1 + Math.min(week, 11) * 0.04;
  const longKm = Math.round(16 * scale);
  // The first two weeks overhaul existing calendar sessions; the rest are new.
  const action = (i: number): PlanRowAction =>
    week === 1 ? (["update", "keep", "create", "update", "delete", "create", "update"][i] as PlanRowAction)
      : week === 2 ? (i === 1 ? "update" : "create")
      : "create";
  const isRaceWeek = week === DEMO_PLAN_WEEKS;
  const taper = phase === "taper";
  const rows: PlanSessionRow[] = [
    { date: start, day: "Mon", sport: "Strength", category: "strength", action: action(0), title: taper ? "Strength: activation" : "Strength: heavy lower body", code: "S 40' heavy-lower", distance_km: null, duration_minutes: taper ? 20 : 40, tss_planned: 30,
      exercises: taper ? ["Activation: bodyweight squat 2x10", "Glute bridge 2x12", "Calf raise 2x12"] : ["Back squat 4x5", "Deadlift 3x5", "Bulgarian split squat 3x6/leg", "Single-leg calf raise 3x10"],
      load: taper ? "RPE 5, no soreness · rest 60\"" : "RPE 8 (2 reps in reserve) · rest 2-3'" },
    { date: demoAddDays(start, 1), day: "Tue", sport: "Run", category: "quality", action: action(1), title: phase === "base" ? "Hills 8x60\"" : "VO2max 6x1 km", code: "I 6x1k r2'", distance_km: Math.round(11 * scale), duration_minutes: 58, tss_planned: 78 },
    { date: demoAddDays(start, 2), day: "Wed", sport: "Run", category: "easy", action: action(2), title: "Easy run", code: "E 10", distance_km: Math.round(9 * scale), duration_minutes: 52, tss_planned: 45 },
    { date: demoAddDays(start, 3), day: "Thu", sport: "Run", category: "quality", action: action(3), title: "Threshold 2x15'", code: "T 2x15' r2'", distance_km: Math.round(12 * scale), duration_minutes: 62, tss_planned: 82,
      time: phase === "base" || phase === "build" ? "07:00" : null },
    ...(phase === "base" || phase === "build"
      ? [{ date: demoAddDays(start, 3), day: "Thu", sport: "Strength", category: "strength" as const, action: action(4), title: "Strength: core & hips", code: "S 30' core-hips", distance_km: null, duration_minutes: 30, tss_planned: 20, time: "18:00",
          exercises: ["Single-leg glute bridge 3x12/leg", "Copenhagen plank 3x25\"/side", "Pallof press 3x12/side", "Hip airplane 3x6/leg"],
          load: "Controlled tempo, add load where easy · rest 45\"" }]
      : []),
    { date: demoAddDays(start, 4), day: "Fri", sport: "Bike", category: "bike", action: action(5), title: "Recovery spin Z1", code: "B 45' Z1", distance_km: null, duration_minutes: 45, tss_planned: 25 },
    isRaceWeek
      ? { date: demoAddDays(start, 6), day: "Sun", sport: "Race", category: "quality", action: "create", title: "CPC Loop Den Haag — Sub-1:26 HM", code: "RACE", distance_km: 21.1, duration_minutes: 86, tss_planned: 140 }
      : { date: demoAddDays(start, 6), day: "Sun", sport: "Run", category: week >= 9 && !down ? "quality" : "easy", action: action(6), title: week >= 9 && !down ? `Long run ${longKm} km +6@HM` : `Long run ${longKm} km`, code: week >= 9 && !down ? `L ${longKm} +6@HM` : `L ${longKm}`, distance_km: longKm, duration_minutes: Math.round(longKm * 5.4), tss_planned: Math.round(longKm * 6.5) },
  ] as PlanSessionRow[];
  const counts = { create: 0, update: 0, delete: 0, keep: 0 };
  for (const r of rows) counts[r.action] += 1;
  const runKm = rows.filter((r) => r.sport === "Run" || r.sport === "Race").reduce((n, r) => n + (r.distance_km ?? 0), 0);
  return {
    week,
    start,
    phase,
    focus: down ? "Down week: absorb the load" : phase === "base" ? "Aerobic base; strength 2x" : phase === "build" ? "HM-pace endurance; heavy strength 2x" : phase === "peak" ? "Race-specific sharpening; strength maintenance" : "Taper: freshen up",
    run_km: Math.round(runKm * 10) / 10,
    bike_minutes: 45,
    strength_sessions: rows.filter((r) => r.sport === "Strength").length,
    tss: rows.reduce((n, r) => n + (r.action === "delete" ? 0 : r.tss_planned ?? 0), 0),
    counts,
    rows,
  };
}

const DEMO_PLAN_WEEK_LIST = Array.from({ length: DEMO_PLAN_WEEKS }, (_, i) => demoPlanWeek(i + 1));

export const DEMO_PLAN: StagedTrainingPlan = {
  version: 1,
  staged_id: "6b1e7c2a-4f0d-4a7e-9a35-2f1d8c9e0b11",
  title: `Sub-1:26 Half Marathon · ${DEMO_PLAN_WEEKS} weeks`,
  mode: "new",
  start_date: DEMO_PLAN_START,
  end_date: "2027-03-14",
  totals: DEMO_PLAN_WEEK_LIST.reduce(
    (t, w) => ({
      ...t,
      sessions: t.sessions + w.rows.length,
      create: t.create + (w.counts?.create ?? 0),
      update: t.update + (w.counts?.update ?? 0),
      delete: t.delete + (w.counts?.delete ?? 0),
      keep: t.keep + (w.counts?.keep ?? 0),
    }),
    { weeks: DEMO_PLAN_WEEKS, sessions: 0, create: 0, update: 0, delete: 0, keep: 0 },
  ),
  weeks: DEMO_PLAN_WEEK_LIST,
};

/** Demo coach opener after Build Plan: proposes a block and asks questions; nothing is built yet. */
export const DEMO_BLOCK_OPENER = `Hey Cyrille! 👋 Let's shape your next block together.

You're heading for **Sub-1:26 at CPC Loop Den Haag on 14 Mar**, then the Rotterdam Marathon. With your 1:27:40 half PR and a steady ~45 km/week lately, here's what I'd propose:

- **16 weeks**, 23 Nov → 14 Mar: base (5) → build (6) → HM-specific (3) → taper (2)
- Peak around **60 km/week**, long run up to **24 km** with HM-pace blocks
- Two quality sessions a week (threshold + HM pace), strength 2x in base and build

Before I put it together, a few things only you can tell me:
1. How many days a week can you run, and which day suits the long run?
2. Any holidays, travel or work peaks between now and March?
3. How's the body feeling right now — any niggles I should plan around?`;

export const DEMO_PLAN_MARKDOWN = `### Block Strategy

16-week build from aerobic base into HM-specific endurance for **CPC Loop Den Haag** (3:1 cycle, 2-week taper).

1. **Volume & Long Runs:** Ramps from ~45 km to **60 km/week** (W11–W13), peaking at a **23 km** (\`+6@HM\`) long run before taper.
2. **Intensity & Rhythm:** Tuesday VO2max/hills and Thursday threshold stay separated by easy Wednesday km and Saturday rest (~80/20 split).
3. **Strength & Cross-Training:** Monday heavy lower and Thursday PM core/hips taper to 1x in peak; Friday's Z1 spin adds low-impact load.
4. **Watchpoints:**
   - Keep Wednesday easy runs below LT1 (141 bpm) once HM-pace long runs start in W9.
   - Maintain single-leg calf raises to protect Achilles resilience before 6x1 km work.

- **${DEMO_PLAN_WEEKS}-week plan staged:** ${DEMO_PLAN.totals.sessions} sessions (${DEMO_PLAN.totals.create} new · ${DEMO_PLAN.totals.update} updated · ${DEMO_PLAN.totals.delete} removed). Review the weeks below and press **Apply to TrainingPeaks**.`;
