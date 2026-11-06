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
  recent_race_times?: string | null;
  injuries?: string | null;
  cross_training_strength?: string | null;
  shoe_rotation?: string | null;
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
  recent_race_times?: string | null;
  injuries?: string | null;
  cross_training_strength?: string | null;
  shoe_rotation?: string | null;
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
  build_weeks: number;
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
}

export type ReportEnvelope =
  | { kind: "checkin"; data: CheckinReportData }
  | { kind: "trend"; data: TrendReportData };

export interface ToolChip {
  name: string;
  label: string;
  state: "start" | "done";
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
  onMessage?: (payload: { text: string; kind: MessageKind }) => void;
  onError?: (message: string) => void;
  onDone?: (sessionId: string) => void;
}
