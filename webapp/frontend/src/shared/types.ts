export type ProfileState = "none" | "needs_onboarding" | "ready";

export type MessageKind =
  | "checkin"
  | "trend"
  | "workout"
  | "audit"
  | "nutrition"
  | "chat";

export interface TrainingPeaksStatus {
  connected: boolean;
  tp_athlete_id?: string | null;
  tp_name?: string | null;
  updated_at?: string | null;
}

export interface NorthStarSummary {
  goal?: string | null;
  race_name?: string | null;
  race_date?: string | null;
}

export interface ProfileSummary {
  firstname: string;
  lastname: string;
  full_name: string;
  location?: string | null;
  goal_type: "single" | "plan";
  active_goal?: string | null;
  active_race_name?: string | null;
  active_date?: string | null;
  /** Start of the current or next block (active sub-goal's start_date, or the single goal's goal_set_date). */
  active_start_date?: string | null;
  weeks_remaining?: number | null;
  north_star?: NorthStarSummary | null;
}

export interface MeResponse {
  email: string;
  runner_id: string | null;
  display_name: string;
  initials: string;
  profile_state: ProfileState;
  tp: TrainingPeaksStatus;
  summary: ProfileSummary | null;
}

export interface SubGoal {
  goal: string;
  race_name?: string | null;
  start_date: string;
  race_date: string;
  taper_weeks?: number | null;
  result?: string | null;
}

export interface NorthStarGoal {
  goal: string;
  race_name?: string | null;
  start_date?: string | null;
  race_date: string;
  taper_weeks?: number | null;
}

export type PersonalRecordKey =
  | "5k"
  | "10k"
  | "10_mile"
  | "half_marathon"
  | "marathon";

export interface PersonalRecord {
  time: string;
  time_s?: number | null;
  date?: string | null;
}

export type PersonalRecords = Partial<
  Record<PersonalRecordKey, PersonalRecord | null>
>;

export type ShoeSlotKey = "easy" | "tempo" | "interval" | "long_run" | "race";

export type ShoeRotation = Partial<Record<ShoeSlotKey, string | null>>;

export interface RunnerProfile {
  firstname?: string | null;
  lastname?: string | null;
  email?: string | null;
  age?: string | null;
  height?: string | null;
  weight?: string | null;
  location?: string | null;
  goal_type?: "single" | "plan" | null;
  training_goal?: string | null;
  timeline?: string | null;
  taper_weeks?: number | null;
  goal_set_date?: string | null;
  north_star?: NorthStarGoal | null;
  sub_goals?: SubGoal[] | null;
  personal_records?: PersonalRecords | null;
  injuries?: string | null;
  cross_training_strength?: string | null;
  shoe_rotation?: ShoeRotation | null;
}

export interface ProfileResponse {
  runner_id: string;
  profile_state: ProfileState;
  tp: TrainingPeaksStatus;
  profile: RunnerProfile;
  summary?: ProfileSummary | null;
}

export interface ProfileUpdatePayload {
  age?: string | null;
  height?: string | null;
  weight?: string | null;
  location?: string | null;
  goal_type: "single" | "plan";
  training_goal?: string | null;
  timeline?: string | null;
  taper_weeks?: number | null;
  north_star?: NorthStarGoal | null;
  sub_goals: Array<{
    goal: string;
    race_name?: string | null;
    start_date: string;
    race_date: string;
    taper_weeks?: number | null;
  }>;
  personal_records?: PersonalRecords | null;
  injuries?: string | null;
  cross_training_strength?: string | null;
  shoe_rotation?: ShoeRotation | null;
}

export interface CheckinPmcPoint {
  date: string;
  ctl: number;
  atl: number;
  tsb: number;
}

export interface CheckinWeekItem {
  week: string | null;
  date_range?: string | null;
  km: number;
  tss: number;
  easy: number;
  quality: number;
  growth_pct?: number | null;
  partial: boolean;
  in_progress?: boolean;
}

export interface CheckinDriver {
  driver: string;
  evidence: string;
  implied: string;
}

export interface CheckinProjection {
  goal_label?: string | null;
  today_s?: number | null;
  race_day_s?: number | null;
  goal_s?: number | null;
  gap_s?: number | null;
  range_s?: [number, number] | null;
  confidence?: string | null;
  stale: boolean;
  readiness?: string | null;
  /** Evidence behind the projection (threshold, goal-pace work, durability, load, health). */
  drivers?: CheckinDriver[];
}

export interface CheckinRecoveryPoint {
  date: string;
  hrv?: number | null;
  rhr?: number | null;
  sleep_h?: number | null;
}

export interface CheckinReportData {
  version: number;
  window: { start: string | null; end: string | null };
  ctl: {
    current: number;
    target: number;
    range: [number, number];
    pct: number;
    weeks_remaining?: number | null;
    required_ramp?: number | null;
    ramp_tier?: "safe" | "aggressive" | "high_risk" | null;
    phase?: string | null;
    pre_taper_ctl?: number | null;
    atl: number;
    tsb: number;
  };
  pmc: CheckinPmcPoint[];
  projection?: CheckinProjection | null;
  weeks: CheckinWeekItem[];
  recovery?: {
    sleep_avg_h?: number | null;
    hrv_latest?: number | null;
    rhr_latest?: number | null;
    series: CheckinRecoveryPoint[];
  } | null;
  lt?: CheckinLtPaces | null;
}

/** Pace (s/km) at LT1 (top of zone 2) / LT2 (LTHR): current 4-week fit vs previous 4 weeks. */
export interface CheckinLtPaces {
  lt1_pace_s?: number | null;
  lt2_pace_s?: number | null;
  lt1_prev_s?: number | null;
  lt2_prev_s?: number | null;
  lt1_hr?: number | null;
  lthr?: number | null;
  lt1_extrapolated?: boolean;
  lt2_extrapolated?: boolean;
}

export interface TrendWeekPoint {
  week: string | null;
  complete: boolean;
  km: number;
  tss: number;
  runs: number;
  quality: number;
  long_km: number;
  ctl?: number | null;
  tsb?: number | null;
  hrv?: number | null;
  hrv_delta_pct?: number | null;
  rhr?: number | null;
  rhr_delta?: number | null;
  sleep_h?: number | null;
  lt1_pace_s?: number | null;
  lt2_pace_s?: number | null;
  lt2_extrapolated?: boolean;
  key_decoupling?: number | null;
  /** Finish time implied by the week's LT2 pace for the goal / north-star distance (s). */
  implied_goal_s?: number | null;
  implied_ns_s?: number | null;
}

export interface TrendProgressItem {
  label?: string | null;
  first?: string | null;
  latest?: string | null;
  best?: string | null;
  change?: string | null;
  arrow?: string | null;
  verdict?: string | null;
}

export interface TrendLevelItem {
  level: number;
  weeks: number;
  streak: number;
  tolerated_share: number;
  hrv_delta_pct?: number | null;
  rhr_delta?: number | null;
  rpe?: number | null;
  proven: boolean;
}

export interface TrendTargetItem {
  target: number;
  status?: string | null;
  /** km/week above the current level (0 when already there). */
  gap_km: number;
}

export interface TrendProjection {
  today_s?: number | null;
  race_day_s?: number | null;
  goal_s?: number | null;
  gap_s?: number | null;
  range_s?: [number, number] | null;
  confidence?: string | null;
  stale?: boolean;
}

export interface TrendGoal {
  training_goal?: string | null;
  label?: string | null;
  kind?: "single" | "sub_goal" | "north_star" | string | null;
  race_date?: string | null;
  weeks_to_race?: number | null;
  before_start?: boolean;
  goal_s?: number | null;
  projection?: TrendProjection | null;
  ctl: {
    current?: number | null;
    target_peak: number;
    range: [number, number];
    required_ramp?: number | null;
    phase?: string | null;
    plan: { week: string; ctl: number }[];
  };
  volume?: TrendVolume | null;
}

/** Weekly running-volume targets of the current block (same per-week numbers as the plan audit). */
export interface TrendVolume {
  block_target_km: number;
  ns_peak_km: number;
  baseline_km?: number | null;
  this_week_km?: number | null;
  first_km?: number | null;
  first_week?: string | null;
  peak_week?: string | null;
  maintain: boolean;
  own_block: boolean;
  plan: { week: string; km: number; phase: string }[];
}

export interface TrendMilestone {
  training_goal: string;
  race_date?: string | null;
  status: "done" | "active" | "upcoming" | string;
  target_equiv_s?: number | null;
  result_equiv_s?: number | null;
}

export interface TrendNorthStar {
  training_goal: string;
  label?: string | null;
  race_name?: string | null;
  race_date?: string | null;
  weeks_to_race?: number | null;
  target_s?: number | null;
  equivalent_s?: number | null;
  gap_s?: number | null;
  ctl_range: [number, number];
  milestones: TrendMilestone[];
}

export interface TrendPaceRow {
  name: string;
  pace: string;
}

export interface TrendReportData {
  version: number;
  window: { start: string | null; end: string | null };
  weeks: TrendWeekPoint[];
  progress: TrendProgressItem[];
  levels: TrendLevelItem[];
  outlook: {
    proven_km?: number | null;
    max_km: number;
    current_km: number;
    targets: TrendTargetItem[];
  };
  key_run_label?: string | null;
  goal?: TrendGoal | null;
  north_star?: TrendNorthStar | null;
  paces?: TrendPaceRow[];
}

export type AuditSessionCategory =
  | "easy"
  | "quality"
  | "bike"
  | "strength"
  | "other";

export interface AuditSession {
  date: string | null;
  sport: string;
  title: string;
  category: AuditSessionCategory;
  km: number;
  minutes: number;
  tss: number;
  completed: boolean;
}

export interface AuditWeek {
  week: string | null;
  date_range?: string | null;
  km: number;
  tss: number;
  easy: number;
  quality: number;
  bike: number;
  strength: number;
  long_run?: string | null;
  /** Running km change vs the previous week (fact; no coded limit). */
  vs_prior_pct?: number | null;
  volume?: AuditWeekVolume | null;
  notes: string[];
  sessions: AuditSession[];
}

/** Planned week's running-volume reference path (null: completed, transition or race week). */
export interface AuditWeekVolume {
  target_km: number;
  block_target_km: number;
  phase: string;
  /** Planned km vs the path value (fact; the coach judges whether it matters). */
  vs_path_pct?: number | null;
}

/** How the weekly km targets are derived (block of the first targeted week); drives the calendar caption. */
export interface AuditVolumeReference {
  goal?: string | null;
  goal_label?: string | null;
  ns_goal?: string | null;
  own_block: boolean;
  block_target_km: number;
  ns_peak_km?: number | null;
  /** Starting level of the path: recent 4-week average, or the previous block's target. */
  start_km?: number | null;
  peak_week?: string | null;
  recovery_every_weeks: number;
}

export interface AuditReportData {
  version: number;
  window: { start: string | null; end: string | null };
  weeks: AuditWeek[];
  volume_reference?: AuditVolumeReference | null;
}

/** One headline metric of the workout banner (pre-formatted by the backend). */
export interface WorkoutTile {
  key: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string | null;
}

export interface WorkoutHrZone {
  label: string;
  name: string;
  pct: number;
  seconds: number;
}

export interface WorkoutReadiness {
  key: "hrv" | "rhr" | "sleep" | string;
  label: string;
  value: number;
  unit: string;
  date?: string | null;
  direction?: "up" | "down" | "flat" | null;
  tone?: "emerald" | "amber" | "rose" | "slate";
}

/** Session-overview banner payload (mirrors `features/workout_analysis/helpers/web_report.py`). */
export interface WorkoutReportData {
  version: number;
  workout_id: string;
  title: string;
  sport: string;
  sport_family: "run" | "bike";
  date: string | null;
  start_time?: string | null;
  location?: string | null;
  structured?: boolean;
  tiles: WorkoutTile[];
  elevation?: {
    gain_m?: number | null;
    loss_m?: number | null;
    /** [[km, metres], ...] */
    profile?: Array<[number, number]> | null;
  } | null;
  hr_zones?: WorkoutHrZone[] | null;
  weather?: {
    temp_c?: number | null;
    feels_like_c?: number | null;
    humidity?: number | null;
    wind_kmh?: number | null;
  } | null;
  readiness?: WorkoutReadiness[] | null;
  other_sessions?: Array<{ id: string; title: string; sport: string }>;
}

export type ReportEnvelope =
  | { kind: "checkin"; data: CheckinReportData }
  | { kind: "trend"; data: TrendReportData }
  | { kind: "audit"; data: AuditReportData }
  | { kind: "workout"; data: WorkoutReportData };

export interface ToolChip {
  name: string;
  label: string;
  state: "start" | "done";
}

/**
 * Structured dashboard feature action (mirrors `webapp/backend/app/quick_actions.py`).
 * The agent runs the skill + data tool directly; only typed chat goes through LLM routing.
 */
export type QuickAction =
  | { skill: "check-in-report" }
  | { skill: "trend-analysis"; weeks?: number }
  | { skill: "plan-audit"; start_date?: string; end_date?: string }
  | { skill: "workout-analysis"; date_str?: string; sport?: "run" | "bike" }
  | { skill: "workout-creator"; staged_id: string }
  | { skill: "plan-builder"; start_date: string; end_date: string; mode?: "new" | "overhaul" }
  | { skill: "plan-builder:apply"; staged_id: string; week: number };

/** One proposed workout / note change staged by the coach (mirrors `helpers/staged_changes.py`). */
export interface StagedChange {
  kind: "workout" | "note";
  action: "create" | "update" | "delete";
  date: string;
  title: string;
  sport?: string;
  replaces_title?: string | null;
  workout_id?: string | null;
  distance_km?: number | null;
  duration_minutes?: number | null;
  tss_planned?: number | null;
  description?: string;
  /** Compact workout-builder summary, e.g. "15' WU · 5× (12' @ 4:25–4:35/km / 2' rec) · 10' CD". */
  structure_summary?: string | null;
  /** First line of the description (the coach's, or the kept workout's) when there is no builder. */
  description_summary?: string | null;
  /** Planned values of the workout an update replaces or a delete removes (the "Current workout" column). */
  replaces?: StagedWorkoutSnapshot | null;
}

/** Planned values of an existing TrainingPeaks workout. */
export interface StagedWorkoutSnapshot {
  title?: string | null;
  date?: string | null;
  sport?: string | null;
  distance_km?: number | null;
  duration_minutes?: number | null;
  tss_planned?: number | null;
  /** Builder summary of the current workout, when TrainingPeaks has one. */
  structure_summary?: string | null;
  /** First line of the current workout's description. */
  description_summary?: string | null;
}

/** Staged set shown with the "Update TrainingPeaks" button. */
export interface StagedChanges {
  staged_id: string;
  changes: StagedChange[];
}

/** Outcome of applying a staged set (marks its card as applied). */
export interface AppliedChanges {
  staged_id: string;
  applied: number;
  failed: number;
}

export type PlanRowAction = "create" | "update" | "delete" | "keep";

/** One dated session of a staged training plan (mirrors `features/plan_builder/helpers/web_payload.py`). */
export interface PlanSessionRow {
  date: string;
  day: string;
  sport: string;
  action: PlanRowAction;
  title: string;
  code?: string | null;
  distance_km?: number | null;
  duration_minutes?: number | null;
  tss_planned?: number | null;
  summary?: string | null;
}

export interface PlanWeekCounts {
  create: number;
  update: number;
  delete: number;
  keep: number;
}

export interface PlanWeek {
  week: number;
  start: string;
  phase: string;
  focus?: string | null;
  run_km?: number | null;
  bike_minutes?: number | null;
  strength_sessions?: number | null;
  tss?: number | null;
  counts?: PlanWeekCounts | null;
  rows: PlanSessionRow[];
}

/** Staged training plan shown with the "Apply to TrainingPeaks" button (state `staged_training_plan`). */
export interface StagedTrainingPlan {
  version: number;
  staged_id: string;
  title: string;
  mode?: "new" | "overhaul" | string;
  start_date: string;
  end_date: string;
  totals: PlanWeekCounts & { weeks: number; sessions: number };
  weeks: PlanWeek[];
}

/** Progress of the week-by-week apply (state `applied_training_plan`, updated after every week). */
export interface AppliedTrainingPlan {
  staged_id: string;
  total_weeks: number;
  weeks_done: number[];
  created: number;
  updated: number;
  deleted: number;
  failed: number;
  failed_weeks: number[];
  done: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  kind: MessageKind;
  timestamp?: number | string | null;
  streaming?: boolean;
  thinking?: boolean;
  tools?: ToolChip[];
  report?: ReportEnvelope | null;
  staged?: StagedChanges | null;
  plan?: StagedTrainingPlan | null;
  error?: string | null;
}

export interface SessionResponse {
  session_id: string | null;
  messages: ChatMessage[];
}

export interface ConnectTpResponse {
  runner_id: string;
  profile_state: ProfileState;
  tp: {
    connected: boolean;
    tp_athlete_id: string;
    tp_name?: string | null;
  };
}

export interface ChatStreamHandlers {
  onSession?: (sessionId: string) => void;
  onStatus?: (phase: string) => void;
  onTool?: (chip: ToolChip) => void;
  onDelta?: (text: string) => void;
  onReport?: (report: ReportEnvelope) => void;
  onStaged?: (staged: StagedChanges) => void;
  onApplied?: (applied: AppliedChanges) => void;
  onPlanStaged?: (plan: StagedTrainingPlan) => void;
  onPlanApplied?: (applied: AppliedTrainingPlan) => void;
  onMessage?: (payload: { text: string; kind: MessageKind }) => void;
  onError?: (message: string) => void;
  onDone?: (sessionId: string) => void;
}
