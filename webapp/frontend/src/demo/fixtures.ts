import type {
  AuditReportData,
  CheckinReportData,
  MeResponse,
  PlanRowAction,
  PlanSessionRow,
  PlanWeek,
  ProfileResponse,
  RacePredictorResponse,
  StagedTrainingPlan,
  TrendReportData,
  TrendWeekPoint,
  WorkoutReportData,
  YearReviewHeatmapDay,
  YearReviewResponse,
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
    active_goal_kind: "sub_goal",
    active_goal_planned: false,
    has_active_race_goal: true,
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

export const DEMO_RACE_PREDICTOR_RESPONSE: RacePredictorResponse = {
  status: "ready",
  reason: null,
  tp_connected: true,
  cached: true,
  active_goal: {
    kind: "sub_goal",
    training_goal: "Sub-1:26 Half Marathon",
    race_name: "CPC Loop Den Haag",
    race_date: "2027-03-14",
    start_date: "2026-10-26",
    goal_label: "Half Marathon",
    planned: false,
    before_start: false,
    weeks_remaining: 18.4,
    sub_goal_step: 2,
    sub_goal_total: 2,
  },
  data: {
    version: 1,
    updated_at: "2026-11-15T09:15:00Z",
    as_of_date: "2026-11-15",
    trigger: "workout_analysis",
    trigger_workout: {
      workout_id: "w_thresh_1",
      date: "2026-11-14",
      title: "Threshold 3 x 10'",
      quality_km: 7.4,
    },
    goal_key: "sub_goal:sub-1:26 half marathon:2027-03-14",
    active_goal: {
      kind: "sub_goal",
      training_goal: "Sub-1:26 Half Marathon",
      race_name: "CPC Loop Den Haag",
      race_date: "2027-03-14",
      start_date: "2026-10-26",
      goal_label: "Half Marathon",
      planned: false,
      before_start: false,
      weeks_remaining: 18.4,
      sub_goal_step: 2,
      sub_goal_total: 2,
    },
    north_star: {
      training_goal: "Sub-2:58 Marathon",
      goal_label: "Marathon",
      race_name: "NN Marathon Rotterdam",
      race_date: "2027-04-11",
      target_s: 10680,
      equivalent_s: 10815,
      gap_s: 135,
    },
    window_weeks: 12,
    key_sessions_count: 11,
    projection: {
      goal_label: "Half Marathon",
      today_s: 5232,
      race_day_s: 5168,
      today_pace_s_per_km: 248.0,
      race_pace_s_per_km: 245.0,
      goal_s: 5160,
      gap_s: 8,
      range_s: [5135, 5245],
      confidence: "High",
      stale: false,
      readiness: "🟢",
      durability: "strong",
      signals: ["goal_pace", "hr_efficiency", "race", "threshold"],
      drivers: [
        {
          driver: "Threshold anchor",
          evidence: "42' of threshold laps @ 3:58/km, 96% LTHR (latest 14 Nov); TP setting 4:00/km",
          implied: "4:06/km (×0.97)",
        },
        {
          driver: "Goal-pace work",
          evidence: "6.4 km @ 4:04/km, 94% LTHR, Pa:Hr 2.8% after 12 km (10 Nov) ✅; 5/5 segments supporting",
          implied: "4:04/km",
        },
        {
          driver: "HR efficiency",
          evidence: "19 steady laps, pace @ 163 bpm",
          implied: "4:07/km",
        },
        {
          driver: "Race efforts",
          evidence: "'Zevenheuvelenloop Warm-Up 10K' 10.0 km in 39:12 (18 Oct), Riegel",
          implied: "4:06/km",
        },
        {
          driver: "Durability",
          evidence: "Longest 22 km, long-run Pa:Hr 3.1% -> strong",
          implied: "ratio 0.97",
        },
        {
          driver: "Load",
          evidence: "CTL 61 → ~74 race day, TSB -5",
          implied: "race-day -1.2%",
        },
        {
          driver: "Health",
          evidence: "HRV +2% vs 28d, RHR -1 bpm, sleep 7.7h (+10 min)",
          implied: "🟢 readiness",
        },
      ],
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
  dynamics: {
    ref_pace_s: 310,
    gct_ms: 252,
    gct_prev_ms: 258,
    vert_ratio_pct: 8.6,
    vert_ratio_prev_pct: 8.95,
    vert_osc_cm: 9.4,
    cadence_spm: 173,
    stride_m: 1.12,
    late_fade: {
      checked: 4,
      faded: 1,
      median_gct_delta_ms: 4.5,
      median_vr_delta_pp: 0.18,
      flagged_runs: [
        {
          date: "2026-11-01",
          title: "Progressive Long Run 24 km",
          scope: "session",
          gct_delta_ms: 14.0,
          vr_delta_pp: 0.72,
          cadence_delta: -4.0,
          stride_delta_pct: -3.1,
          speed_delta_pct: -2.0,
        },
      ],
    },
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
    { week: "2026-05-18", complete: true, km: 48.0, tss: 305, runs: 5, quality: 1, long_km: 16, ctl: 43.2, tsb: 1.4, hrv: 61, rhr: 49, sleep_h: 7.3, lt1_pace_s: 318, lt2_pace_s: 262, key_decoupling: 5.4, rd_gct_ms: 264, rd_vert_ratio_pct: 9.25, rd_vert_osc_cm: 10.0, rd_cadence: 169, rd_stride_m: 1.08, rd_fade_runs: 1, rd_fade_checked: 3 },
    { week: "2026-06-01", complete: true, km: 52.5, tss: 332, runs: 5, quality: 2, long_km: 18, ctl: 45.1, tsb: -1.8, hrv: 62, rhr: 48, sleep_h: 7.4, lt1_pace_s: 316, lt2_pace_s: 261, key_decoupling: 4.9, rd_gct_ms: 263, rd_vert_ratio_pct: 9.18, rd_vert_osc_cm: 9.9, rd_cadence: 170, rd_stride_m: 1.08, rd_fade_runs: 1, rd_fade_checked: 3 },
    { week: "2026-06-15", complete: true, km: 56.2, tss: 355, runs: 5, quality: 2, long_km: 19, ctl: 47.0, tsb: -2.4, hrv: 63, rhr: 48, sleep_h: 7.5, lt1_pace_s: 314, lt2_pace_s: 259, key_decoupling: 4.5, rd_gct_ms: 261, rd_vert_ratio_pct: 9.10, rd_vert_osc_cm: 9.8, rd_cadence: 170, rd_stride_m: 1.09, rd_fade_runs: 0, rd_fade_checked: 3 },
    { week: "2026-06-29", complete: true, km: 46.0, tss: 284, runs: 5, quality: 1, long_km: 16, ctl: 46.4, tsb: 5.1, hrv: 65, rhr: 47, sleep_h: 7.7, lt1_pace_s: 313, lt2_pace_s: 258, key_decoupling: 3.9, rd_gct_ms: 260, rd_vert_ratio_pct: 9.04, rd_vert_osc_cm: 9.8, rd_cadence: 170, rd_stride_m: 1.09, rd_fade_runs: 0, rd_fade_checked: 2 },
    { week: "2026-07-13", complete: true, km: 59.4, tss: 378, runs: 6, quality: 2, long_km: 20, ctl: 48.9, tsb: -3.2, hrv: 63, rhr: 48, sleep_h: 7.4, lt1_pace_s: 312, lt2_pace_s: 257, key_decoupling: 4.1, rd_gct_ms: 259, rd_vert_ratio_pct: 8.98, rd_vert_osc_cm: 9.7, rd_cadence: 171, rd_stride_m: 1.09, rd_fade_runs: 1, rd_fade_checked: 4 },
    { week: "2026-07-27", complete: true, km: 62.8, tss: 398, runs: 6, quality: 2, long_km: 21, ctl: 50.8, tsb: -3.7, hrv: 64, rhr: 47, sleep_h: 7.5, lt1_pace_s: 311, lt2_pace_s: 256, key_decoupling: 3.8, rd_gct_ms: 258, rd_vert_ratio_pct: 8.92, rd_vert_osc_cm: 9.7, rd_cadence: 171, rd_stride_m: 1.10, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-08-10", complete: true, km: 64.5, tss: 410, runs: 6, quality: 2, long_km: 22, ctl: 52.4, tsb: -3.5, hrv: 64, rhr: 47, sleep_h: 7.6, lt1_pace_s: 309, lt2_pace_s: 255, key_decoupling: 3.6, rd_gct_ms: 257, rd_vert_ratio_pct: 8.88, rd_vert_osc_cm: 9.6, rd_cadence: 171, rd_stride_m: 1.10, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-08-24", complete: true, km: 53.0, tss: 330, runs: 5, quality: 1, long_km: 18, ctl: 51.9, tsb: 4.6, hrv: 66, rhr: 46, sleep_h: 7.8, lt1_pace_s: 307, lt2_pace_s: 254, key_decoupling: 3.3, rd_gct_ms: 256, rd_vert_ratio_pct: 8.82, rd_vert_osc_cm: 9.6, rd_cadence: 172, rd_stride_m: 1.10, rd_fade_runs: 0, rd_fade_checked: 3 },
    { week: "2026-09-07", complete: true, km: 66.8, tss: 428, runs: 6, quality: 2, long_km: 22, ctl: 54.6, tsb: -4.0, hrv: 65, rhr: 47, sleep_h: 7.5, lt1_pace_s: 306, lt2_pace_s: 253, key_decoupling: 3.2, rd_gct_ms: 255, rd_vert_ratio_pct: 8.76, rd_vert_osc_cm: 9.5, rd_cadence: 172, rd_stride_m: 1.11, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-09-21", complete: true, km: 70.4, tss: 452, runs: 6, quality: 2, long_km: 23, ctl: 57.1, tsb: -4.5, hrv: 66, rhr: 46, sleep_h: 7.6, lt1_pace_s: 304, lt2_pace_s: 252, key_decoupling: 3.0, rd_gct_ms: 254, rd_vert_ratio_pct: 8.71, rd_vert_osc_cm: 9.5, rd_cadence: 172, rd_stride_m: 1.11, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-10-05", complete: true, km: 68.2, tss: 438, runs: 6, quality: 2, long_km: 22, ctl: 58.0, tsb: -2.1, hrv: 67, rhr: 46, sleep_h: 7.7, lt1_pace_s: 304, lt2_pace_s: 251, key_decoupling: 2.8, rd_gct_ms: 253, rd_vert_ratio_pct: 8.66, rd_vert_osc_cm: 9.4, rd_cadence: 173, rd_stride_m: 1.11, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-10-19", complete: true, km: 69.8, tss: 446, runs: 6, quality: 2, long_km: 23, ctl: 59.4, tsb: -4.3, hrv: 67, rhr: 46, sleep_h: 7.6, lt1_pace_s: 302, lt2_pace_s: 249, key_decoupling: 2.7, rd_gct_ms: 253, rd_vert_ratio_pct: 8.63, rd_vert_osc_cm: 9.4, rd_cadence: 173, rd_stride_m: 1.12, rd_fade_runs: 0, rd_fade_checked: 4 },
    { week: "2026-10-26", complete: true, km: 73.5, tss: 472, runs: 6, quality: 2, long_km: 24, ctl: 61.4, tsb: -4.8, hrv: 68, rhr: 46, sleep_h: 7.8, lt1_pace_s: 300, lt2_pace_s: 248, key_decoupling: 2.5, rd_gct_ms: 252, rd_vert_ratio_pct: 8.60, rd_vert_osc_cm: 9.4, rd_cadence: 173, rd_stride_m: 1.12, rd_fade_runs: 1, rd_fade_checked: 4 },
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
  dynamics: {
    ref_pace_s: 310,
    bands: [
      { band: "Easy", minutes: 420, pace_s: 312, cadence: 172, stride_m: 1.11, gct_ms: 254, vert_osc_cm: 9.4, vert_ratio_pct: 8.47 },
      { band: "Steady / MP", minutes: 95, pace_s: 274, cadence: 176, stride_m: 1.24, gct_ms: 238, vert_osc_cm: 9.6, vert_ratio_pct: 7.74 },
      { band: "Threshold", minutes: 64, pace_s: 247, cadence: 180, stride_m: 1.34, gct_ms: 224, vert_osc_cm: 9.8, vert_ratio_pct: 7.31 },
    ],
    speed_modulation: {
      from_band: "Easy",
      to_band: "Threshold",
      speed_gain_pct: 25.8,
      cadence_from: 172,
      cadence_to: 180,
      cadence_share_pct: 20,
      stride_from_m: 1.11,
      stride_to_m: 1.34,
      stride_share_pct: 80,
    },
    late_fade: {
      checked: 18,
      faded: 3,
      median_gct_delta_ms: 3.5,
      median_vr_delta_pp: 0.14,
      flagged_runs: [
        {
          date: "2026-11-01",
          title: "Progressive Long Run 24 km",
          scope: "session",
          gct_delta_ms: 14.0,
          vr_delta_pp: 0.72,
          cadence_delta: -4.0,
          stride_delta_pct: -3.1,
          speed_delta_pct: -2.0,
        },
      ],
    },
  },
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
  running_dynamics: {
    cadence_spm: 178,
    stride_m: 1.19,
    gct_ms: 238,
    vert_osc_cm: 9.5,
    vert_ratio_pct: 7.98,
    gct_balance_pct: null,
    late_drift: {
      scope: "reps (3x 10' @ T)",
      speed_delta_pct: -0.6,
      gct_delta_ms: 3.0,
      cadence_delta: -1.0,
      stride_delta_pct: -0.8,
      vr_delta_pp: 0.12,
      fatigue_flag: false,
    },
  },
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

function buildDemoYearHeatmap(): Array<{ week: string; days: YearReviewHeatmapDay[] }> {
  const raceMap: Record<string, string> = {
    "2026-01-18": "Winter 10-Mile Benchmark",
    "2026-03-22": "CPC Loop Den Haag Half Marathon",
    "2026-06-14": "Amsterdam Summer Track 5K",
    "2026-10-18": "Zevenheuvelenloop Warm-Up 10K",
  };
  const start = new Date(Date.UTC(2025, 11, 1)); // Monday Dec 1, 2025
  const cutoff = "2026-11-25";
  const weeks: Array<{ week: string; days: YearReviewHeatmapDay[] }> = [];
  for (let w = 0; w < 52; w += 1) {
    const mon = new Date(start.getTime() + w * 7 * 86400_000);
    const weekIso = mon.toISOString().slice(0, 10);
    const days: YearReviewHeatmapDay[] = [];
    for (let d = 0; d < 7; d += 1) {
      const cur = new Date(mon.getTime() + d * 86400_000);
      const iso = cur.toISOString().slice(0, 10);
      if (iso > cutoff) {
        days.push({ date: iso, km: 0, level: -1, is_race: false, race_name: null });
        continue;
      }
      const raceName = raceMap[iso] ?? null;
      const seed = (w * 37 + d * 17 + 13) % 100;
      let km = 0;
      if (raceName) {
        km = iso === "2026-03-22" ? 21.1 : iso === "2026-06-14" ? 5.0 : iso === "2026-10-18" ? 10.0 : 16.1;
      } else if (d === 6) {
        km = w >= 38 && w <= 44 ? 26.5 : seed > 20 ? 18.0 : 12.0;
      } else if (d === 2) {
        km = seed > 15 ? 13.5 : 10.0;
      } else if (d === 1 || d === 4) {
        km = seed > 25 ? 10.2 : seed > 10 ? 6.5 : 0;
      } else if (d === 3) {
        km = seed > 35 ? 9.5 : 5.5;
      } else if (d === 5) {
        km = seed > 60 ? 5.0 : 0;
      }
      const level = km <= 0 ? 0 : km < 7 ? 1 : km < 13 ? 2 : km < 20 ? 3 : 4;
      days.push({ date: iso, km, level, is_race: Boolean(raceName), race_name: raceName });
    }
    weeks.push({ week: weekIso, days });
  }
  return weeks;
}

const DEMO_YEAR_HEATMAP_WEEKS = buildDemoYearHeatmap();

export const DEMO_AVAILABLE_YEARS = [
  { year: 2026, total_run_km: 2486.0, total_workouts: 298, races_count: 4, is_complete: false, as_of_date: "2026-11-25" },
  { year: 2025, total_run_km: 2140.0, total_workouts: 264, races_count: 2, is_complete: true, as_of_date: "2025-12-31" },
  { year: 2024, total_run_km: 1892.0, total_workouts: 238, races_count: 2, is_complete: true, as_of_date: "2024-12-31" },
  { year: 2023, total_run_km: 1540.0, total_workouts: 196, races_count: 1, is_complete: true, as_of_date: "2023-12-31" },
];

export const DEMO_YEAR_REVIEW_RESPONSE: YearReviewResponse = {
  status: "ready",
  year: 2026,
  available_years: DEMO_AVAILABLE_YEARS,
  tp_connected: true,
  cached: true,
  data: {
    version: 5,
    year: 2026,
    is_complete: false,
    updated_at: "2026-11-25T09:00:00Z",
    as_of_date: "2026-11-25",
    last_computed_date: "2026-11-25",
    sync_mode: "incremental",
    runner_name: "Cyrille Visser",
    window: { start: "2026-01-01", end: "2026-11-25", year_end: "2026-12-31", weeks: 47 },
    coverage: {
      total_workouts: 298,
      total_runs: 218,
      analyzed_runs: 186,
      training_log_start: "2025-12-04",
      training_log_end: "2026-11-24",
    },
    kpis: {
      total_run_km: 2486.0,
      avg_weekly_run_km: 48.2,
      total_runs: 218,
      total_workouts: 298,
      total_hours: 268.3,
      run_hours: 214.0,
      bike_hours: 32.1,
      strength_hours: 22.2,
      ctl_start: 42.0,
      ctl_end: 61.0,
      ctl_delta: 19.0,
      ctl_delta_pct: 45,
      ctl_peak: 68.0,
      ctl_peak_date: "2026-09-27",
      total_tss: 17420,
      active_weeks: 49,
      total_weeks: 52,
      active_weeks_pct: 94,
      longest_streak_weeks: 18,
      peak_week_km: 78.2,
      peak_week_date: "2026-09-14",
    },
    monthly: [
      {
        month: "2026-01", label: "Jan", km: 198, runs: 18, hours: 21.0, tss: 1340, ctl: 49, partial: false, future: false,
        races: [{ date: "2026-01-18", name: "Winter 10-Mile Benchmark", short_label: "10M", duration_s: 3914, is_pr: false, badge: "C Race" }],
      },
      { month: "2026-02", label: "Feb", km: 246, runs: 20, hours: 25.4, tss: 1620, ctl: 56, partial: false, future: false, races: [] },
      {
        month: "2026-03", label: "Mar", km: 232, runs: 19, hours: 24.0, tss: 1560, ctl: 58, partial: false, future: false,
        races: [{ date: "2026-03-22", name: "CPC Loop Den Haag Half Marathon", short_label: "HM", duration_s: 5268, is_pr: true, badge: "A Race" }],
      },
      { month: "2026-04", label: "Apr", km: 185, runs: 17, hours: 19.6, tss: 1290, ctl: 50, partial: false, future: false, races: [] },
      { month: "2026-05", label: "May", km: 204, runs: 18, hours: 21.8, tss: 1410, ctl: 55, partial: false, future: false, races: [] },
      {
        month: "2026-06", label: "Jun", km: 228, runs: 20, hours: 24.1, tss: 1580, ctl: 60, partial: false, future: false,
        races: [{ date: "2026-06-14", name: "Amsterdam Summer Track 5K", short_label: "5K", duration_s: 1121, is_pr: true, badge: "B Race" }],
      },
      { month: "2026-07", label: "Jul", km: 212, runs: 18, hours: 22.8, tss: 1460, ctl: 58, partial: false, future: false, races: [] },
      { month: "2026-08", label: "Aug", km: 241, runs: 20, hours: 25.9, tss: 1690, ctl: 64, partial: false, future: false, races: [] },
      { month: "2026-09", label: "Sep", km: 268, runs: 21, hours: 28.4, tss: 1890, ctl: 68, partial: false, future: false, races: [] },
      {
        month: "2026-10", label: "Oct", km: 218, runs: 18, hours: 23.0, tss: 1510, ctl: 68.2, ctl_peak_date: "2026-10-11", partial: false, future: false,
        races: [{ date: "2026-10-18", name: "Zevenheuvelenloop Warm-Up 10K", short_label: "10K", duration_s: 2352, is_pr: true, badge: "Sub-Goal" }],
      },
      { month: "2026-11", label: "Nov", km: 182, runs: 13, hours: 14.1, tss: 890, ctl: 61, partial: true, future: false, races: [] },
      { month: "2026-12", label: "Dec", km: 0, runs: 0, hours: 0, tss: 0, ctl: null, partial: false, future: true, races: [] },
    ],
    weekly: DEMO_YEAR_HEATMAP_WEEKS.map((wk, idx) => {
      const km = Math.round(wk.days.reduce((s, d) => s + d.km, 0) * 10) / 10;
      const runs = wk.days.filter((d) => d.km > 0).length;
      const longKm = Math.max(0, ...wk.days.map((d) => d.km));
      const raceDay = wk.days.find((d) => d.is_race);
      return {
        week: wk.week,
        km,
        runs,
        sessions: runs + (idx % 2 === 0 ? 2 : 1),
        tss: Math.round(km * 6.8),
        long_km: longKm,
        ctl: Math.round((42 + Math.sin(idx / 7) * 5 + (idx / 51) * 20) * 10) / 10,
        partial: idx === 51,
        races: raceDay
          ? [
              {
                date: raceDay.date,
                name: raceDay.race_name || "Race",
                short_label:
                  raceDay.date === "2026-03-22"
                    ? "HM"
                    : raceDay.date === "2026-06-14"
                      ? "5K"
                      : raceDay.date === "2026-10-18"
                        ? "10K"
                        : "10M",
                duration_s:
                  raceDay.date === "2026-03-22"
                    ? 5268
                    : raceDay.date === "2026-06-14"
                      ? 1121
                      : raceDay.date === "2026-10-18"
                        ? 2352
                        : 3914,
                is_pr: raceDay.date !== "2026-01-18",
                badge: raceDay.date === "2026-10-18" ? "Sub-Goal" : raceDay.date === "2026-03-22" ? "A Race" : "B Race",
              },
            ]
          : [],
      };
    }),
    races: [
      {
        date: "2026-10-18",
        workout_id: "w_race_10k",
        name: "Zevenheuvelenloop Warm-Up 10K",
        badge: "Sub-Goal",
        priority: null,
        short_label: "10K",
        distance_label: "10K",
        distance_km: 10.0,
        duration_s: 2352,
        pace_s: 235.2,
        avg_hr: 174,
        pct_lthr: 98,
        pa_hr: 2.1,
        ctl: 63.0,
        is_pr: true,
        goal_text: "Sub-39:30 10K",
        goal_gap_s: -18,
        note: "Strong negative split",
      },
      {
        date: "2026-06-14",
        workout_id: "w_race_5k",
        name: "Amsterdam Summer Track 5K",
        badge: "B Race",
        priority: "B",
        short_label: "5K",
        distance_label: "5K",
        distance_km: 5.0,
        duration_s: 1121,
        pace_s: 224.2,
        avg_hr: 178,
        pct_lthr: 100,
        pa_hr: null,
        ctl: 60.0,
        is_pr: true,
        goal_text: null,
        goal_gap_s: null,
        note: "Strong negative split",
      },
      {
        date: "2026-03-22",
        workout_id: "w_race_hm",
        name: "CPC Loop Den Haag Half Marathon",
        badge: "A Race",
        priority: "A",
        short_label: "HM",
        distance_label: "Half Marathon",
        distance_km: 21.1,
        duration_s: 5268,
        pace_s: 249.7,
        avg_hr: 169,
        pct_lthr: 95,
        pa_hr: 2.9,
        ctl: 58.0,
        is_pr: true,
        goal_text: null,
        goal_gap_s: null,
        note: "Peak spring race",
      },
      {
        date: "2026-01-18",
        workout_id: "w_race_10m",
        name: "Winter 10-Mile Benchmark",
        badge: "C Race",
        priority: "C",
        short_label: "10M",
        distance_label: "10 Mile",
        distance_km: 16.1,
        duration_s: 3914,
        pace_s: 243.1,
        avg_hr: 166,
        pct_lthr: 93,
        pa_hr: 3.4,
        ctl: 49.0,
        is_pr: false,
        goal_text: null,
        goal_gap_s: null,
        note: "Base-phase opener",
      },
    ],
    fitness_shift: [
      { key: "lt2_pace_s", label: "Pace @ LT2 (Threshold)", start: "4:14/km", latest: "3:59/km", delta: "-15 s/km", arrow: "↓", verdict: "improving" },
      { key: "lt1_pace_s", label: "Pace @ LT1 (Aerobic Z2)", start: "4:56/km", latest: "4:41/km", delta: "-15 s/km", arrow: "↓", verdict: "improving" },
      { key: "rhr", label: "Resting Heart Rate", start: "52 bpm", latest: "48 bpm", delta: "-4 bpm", arrow: "↓", verdict: "improving" },
      { key: "hrv", label: "HRV (Morning Avg)", start: "56 ms", latest: "64 ms", delta: "+14%", arrow: "↑", verdict: "improving" },
      { key: "weekly_km", label: "Avg Weekly Volume", start: "39 km/wk", latest: "54 km/wk", delta: "+38%", arrow: "↑", verdict: "improving" },
    ],
    peaks: [
      { pr_type: "speed1K", distance: "1 km", time_s: 206, time: "3:26", pace_s: 206.0, pace: "3:26/km", date: "2026-06-14", workout_id: "w_race_5k", workout_title: "Amsterdam Summer Track 5K", all_time_pr: false, profile_pr_time: null, profile_pr_date: null },
      { pr_type: "speed5K", distance: "5 km", time_s: 1121, time: "18:41", pace_s: 224.2, pace: "3:44/km", date: "2026-06-14", workout_id: "w_race_5k", workout_title: "Amsterdam Summer Track 5K", all_time_pr: true, profile_pr_time: "18:41", profile_pr_date: "2026-06-14" },
      { pr_type: "speed10K", distance: "10 km", time_s: 2352, time: "39:12", pace_s: 235.2, pace: "3:55/km", date: "2026-10-18", workout_id: "w_race_10k", workout_title: "Zevenheuvelenloop Warm-Up 10K", all_time_pr: true, profile_pr_time: "39:12", profile_pr_date: "2026-10-18" },
      { pr_type: "speedHalfMarathon", distance: "Half Marathon", time_s: 5268, time: "1:27:48", pace_s: 249.7, pace: "4:10/km", date: "2026-03-22", workout_id: "w_race_hm", workout_title: "CPC Loop Den Haag Half Marathon", all_time_pr: false, profile_pr_time: "1:26:50", profile_pr_date: "2024-03-10" },
    ],
    milestones: {
      longest_run: { km: 32.4, date: "2026-09-20", title: "Long Run 32 km" },
      peak_week: { km: 78.2, date: "2026-09-14" },
      peak_month: { km: 268.0, label: "Sep", month: "2026-09" },
    },
    mix: {
      sports: [
        { key: "running", label: "Running", hours: 214.0, sessions: 218, pct: 80 },
        { key: "cycling", label: "Cycling / Cross", hours: 32.1, sessions: 34, pct: 12 },
        { key: "strength", label: "Strength & Mobility", hours: 22.2, sessions: 46, pct: 8 },
      ],
      run_breakdown: {
        easy_pct: 77,
        quality_pct: 14,
        long_race_pct: 9,
        easy_runs: 168,
        quality_runs: 30,
        long_race_runs: 20,
      },
    },
    heatmap: {
      weeks: DEMO_YEAR_HEATMAP_WEEKS,
      run_days: 218,
      longest_streak_weeks: 18,
    },
  },
};
