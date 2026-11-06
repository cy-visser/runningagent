import type {
  ChatMessage,
  ChatStreamHandlers,
  ConnectTpResponse,
  MeResponse,
  ProfileResponse,
  ProfileUpdatePayload,
  SessionResponse,
} from "../types";
import {
  DEMO_CHECKIN_DATA,
  DEMO_CHECKIN_MARKDOWN,
  DEMO_ME_ONBOARDING,
  DEMO_ME_READY,
  DEMO_PROFILE_RESPONSE,
  DEMO_TREND_DATA,
  DEMO_TREND_MARKDOWN,
} from "./fixtures";

function currentDemoPreset(): string {
  if (typeof window === "undefined") return "ready";
  const params = new URLSearchParams(window.location.search);
  return params.get("view") || "ready";
}

let demoMeState: MeResponse | null = null;
let demoProfileState: ProfileResponse = structuredClone(DEMO_PROFILE_RESPONSE);

function ensureDemoState(): MeResponse {
  if (!demoMeState) {
    const preset = currentDemoPreset();
    demoMeState = structuredClone(
      preset === "onboarding" ? DEMO_ME_ONBOARDING : DEMO_ME_READY,
    );
  }
  return demoMeState;
}

export async function demoFetchMe(): Promise<MeResponse> {
  return structuredClone(ensureDemoState());
}

export async function demoFetchProfile(): Promise<ProfileResponse> {
  return structuredClone(demoProfileState);
}

export async function demoUpdateProfile(
  payload: ProfileUpdatePayload,
): Promise<ProfileResponse> {
  const updated = structuredClone(demoProfileState);
  updated.profile.age = payload.age ?? null;
  updated.profile.height = payload.height ?? null;
  updated.profile.weight = payload.weight ?? null;
  updated.profile.location = payload.location ?? null;
  updated.profile.goal_type = payload.goal_type;
  updated.profile.recent_race_times = payload.recent_race_times ?? null;
  updated.profile.injuries = payload.injuries ?? null;
  updated.profile.cross_training_strength = payload.cross_training_strength ?? null;
  updated.profile.shoe_rotation = payload.shoe_rotation ?? null;

  if (payload.goal_type === "single") {
    updated.profile.training_goal = payload.training_goal ?? null;
    updated.profile.timeline = payload.timeline ?? null;
    updated.profile.taper_weeks = payload.taper_weeks ?? null;
    updated.profile.north_star = null;
    updated.profile.sub_goals = [];
    if (updated.summary) {
      updated.summary.goal_type = "single";
      updated.summary.active_goal = payload.training_goal ?? null;
      updated.summary.active_date = payload.timeline ?? null;
      updated.summary.north_star = null;
    }
  } else {
    updated.profile.north_star = payload.north_star ?? null;
    updated.profile.sub_goals = payload.sub_goals.map((sg) => ({
      ...sg,
      result: null,
    }));
    if (updated.summary && payload.north_star) {
      updated.summary.goal_type = "plan";
      updated.summary.north_star = {
        goal: payload.north_star.goal,
        race_name: payload.north_star.race_name,
        race_date: payload.north_star.race_date,
      };
      if (payload.sub_goals.length > 0) {
        updated.summary.active_goal = payload.sub_goals[0].goal;
        updated.summary.active_race_name = payload.sub_goals[0].race_name ?? null;
        updated.summary.active_date = payload.sub_goals[0].race_date;
      }
    }
  }
  demoProfileState = updated;
  if (demoMeState) {
    demoMeState.summary = updated.summary ?? demoMeState.summary;
    demoMeState.profile_state = "ready";
  }
  return structuredClone(updated);
}

export async function demoConnectTrainingPeaks(
  cookie: string,
): Promise<ConnectTpResponse> {
  await new Promise((r) => setTimeout(r, 350));
  if (cookie.trim().length < 8) {
    throw new Error("Cookie looks too short.");
  }
  const me = ensureDemoState();
  me.runner_id = me.runner_id || "alex_vermeer";
  me.profile_state = me.profile_state === "ready" ? "ready" : "needs_onboarding";
  me.tp = {
    connected: true,
    tp_athlete_id: "4819204",
    tp_name: me.display_name,
    updated_at: new Date().toISOString(),
  };
  return {
    runner_id: me.runner_id,
    profile_state: me.profile_state,
    tp: {
      connected: true,
      tp_athlete_id: "4819204",
      tp_name: me.display_name,
    },
  };
}

export async function demoFetchSession(): Promise<SessionResponse> {
  const preset = currentDemoPreset();
  const messages: ChatMessage[] = [];
  if (preset === "checkin") {
    messages.push(
      {
        id: "u-1",
        role: "user",
        text: "Checking in",
        kind: "chat",
      },
      {
        id: "a-1",
        role: "assistant",
        text: DEMO_CHECKIN_MARKDOWN,
        kind: "checkin",
        report: { kind: "checkin", data: DEMO_CHECKIN_DATA },
      },
    );
  } else if (preset === "trend") {
    messages.push(
      {
        id: "u-2",
        role: "user",
        text: "Trend analysis for the past 6 months",
        kind: "chat",
      },
      {
        id: "a-2",
        role: "assistant",
        text: DEMO_TREND_MARKDOWN,
        kind: "trend",
        report: { kind: "trend", data: DEMO_TREND_DATA },
      },
    );
  }
  return {
    session_id: "demo-session-1",
    messages,
  };
}

export async function demoCreateNewSession(): Promise<SessionResponse> {
  return {
    session_id: `demo-session-${Date.now()}`,
    messages: [],
  };
}

export async function demoStreamChat(
  params: { message: string; sessionId?: string | null },
  handlers: ChatStreamHandlers,
): Promise<void> {
  const sid = params.sessionId || "demo-session-1";
  handlers.onSession?.(sid);
  handlers.onStatus?.("thinking");
  await new Promise((r) => setTimeout(r, 180));

  const lower = params.message.toLowerCase();
  if (lower.includes("check") && lower.includes("in")) {
    handlers.onTool?.({
      name: "fetch_checkin_data",
      label: "Pulling 14 days of TrainingPeaks data",
      state: "start",
    });
    await new Promise((r) => setTimeout(r, 260));
    handlers.onTool?.({
      name: "fetch_checkin_data",
      label: "Pulling 14 days of TrainingPeaks data",
      state: "done",
    });
    handlers.onReport?.({ kind: "checkin", data: DEMO_CHECKIN_DATA });
    handlers.onMessage?.({ text: DEMO_CHECKIN_MARKDOWN, kind: "checkin" });
  } else if (lower.includes("trend") || lower.includes("6 month")) {
    handlers.onTool?.({
      name: "fetch_trend_data",
      label: "Analysing 6-month training log & load capacity",
      state: "start",
    });
    await new Promise((r) => setTimeout(r, 260));
    handlers.onTool?.({
      name: "fetch_trend_data",
      label: "Analysing 6-month training log & load capacity",
      state: "done",
    });
    handlers.onReport?.({ kind: "trend", data: DEMO_TREND_DATA });
    handlers.onMessage?.({ text: DEMO_TREND_MARKDOWN, kind: "trend" });
  } else if (lower.includes("audit")) {
    handlers.onTool?.({
      name: "fetch_schedule_audit_data",
      label: "Auditing weekly schedule & calendar notes",
      state: "start",
    });
    await new Promise((r) => setTimeout(r, 220));
    handlers.onTool?.({
      name: "fetch_schedule_audit_data",
      label: "Auditing weekly schedule & calendar notes",
      state: "done",
    });
    handlers.onMessage?.({
      kind: "audit",
      text: `### Current Week Schedule Audit (Nov 2 – Nov 8)\n\n| Day | Planned Session | Status | Coach Note |\n| :--- | :--- | :--- | :--- |\n| **Tue** | 12 km w/ 5×1 km @ 3:48/km | 🟢 Completed | Nailed splits (3:47 avg), HR peaked at 176 bpm |\n| **Thu** | 14 km Tempo Cruise (2×20 min @ 4:02/km) | 🟢 Balanced | Ideal spacing 48h after Tuesday intervals |\n| **Sat** | 10 km Easy + 6×20s tarmac strides | 🟡 Note | Keep strides strictly flat for Achilles care |\n| **Sun** | 22 km Progressive Long Run | 🟢 Key session | Brings weekly total to **71.5 km** (+0.8 CTL) |`,
    });
  } else {
    handlers.onMessage?.({
      kind: "chat",
      text: `Got it! Based on your **Sub-1:26 Half Marathon** block (61.4 CTL, TSB -4.8), keep today's aerobic effort relaxed at **4:55–5:10/km** below 141 bpm so you're fresh for Thursday's threshold cruise.`,
    });
  }

  handlers.onDone?.(sid);
}
