import { useState } from "react";
import {
  Activity,
  ArrowRight,
  CalendarCheck,
  CalendarRange,
  CheckCircle2,
  ClipboardCheck,
  Compass,
  Loader2,
  Send,
  Sparkles,
  Target,
  TrendingUp,
  UserCheck,
} from "lucide-react";
import { formatShortDate, greetingForHour } from "../shared/format";
import type {
  AppliedTrainingPlan,
  ChatMessage,
  MeResponse,
  ProfileSummary,
  QuickAction,
} from "../shared/types";
import { ChatFeed, type PlanApplying } from "./ChatFeed";

/** Maximum audit horizon (in ISO weeks, starting Monday of the current week) when a goal race is set. */
export const AUDIT_MAX_WEEKS = 4;

export interface AuditAction {
  title: string;
  subtitle: string;
  /** Shown as the runner's message in the feed. */
  prompt: string;
  /** Structured action: the agent runs the audit with these dates, no LLM routing. */
  action: QuickAction;
}

const DEFAULT_AUDIT_SUBTITLE =
  "Cross-check planned workouts, calendar notes, 80/20 intensity balance & safe ramp rate";

/** Local-date YYYY-MM-DD (not UTC, so late-evening users don't get tomorrow). */
function localIsoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function addDays(d: Date, days: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);
}

/**
 * Audit card config. With an upcoming goal race the audit runs from Monday of the current week
 * until race day (capped at AUDIT_MAX_WEEKS weeks); otherwise it audits the current week.
 */
export function auditScheduleAction(
  summary: ProfileSummary | null | undefined,
  now: Date = new Date(),
): AuditAction {
  const today = localIsoDate(now);
  const race = summary?.active_date?.slice(0, 10);
  if (!race || !/^\d{4}-\d{2}-\d{2}$/.test(race) || race < today) {
    return {
      title: "Audit Plan – Current Week",
      subtitle: DEFAULT_AUDIT_SUBTITLE,
      prompt: "Audit my plan for this week",
      action: { skill: "schedule-audit" },
    };
  }

  const monday = addDays(now, -((now.getDay() + 6) % 7));
  const start = localIsoDate(monday);
  const capEnd = localIsoDate(addDays(monday, AUDIT_MAX_WEEKS * 7 - 1));
  const capped = race > capEnd;
  const end = capped ? capEnd : race;
  const goal = summary?.active_goal?.trim();
  const goalText = goal ? ` (${goal})` : "";
  const action: QuickAction = { skill: "schedule-audit", start_date: start, end_date: end };

  if (capped) {
    return {
      title: `Audit Plan – Next ${AUDIT_MAX_WEEKS} Weeks`,
      subtitle: `${formatShortDate(start)} → ${formatShortDate(end)} · toward ${goal || "race day"} on ${formatShortDate(race)}`,
      prompt:
        `Audit my plan for the next ${AUDIT_MAX_WEEKS} weeks, from ${start} to ${end}, ` +
        `building toward my race on ${race}${goalText}.`,
      action,
    };
  }
  return {
    title: "Audit Plan – Until Race Day",
    subtitle: `${formatShortDate(start)} → ${formatShortDate(race)}${goal ? ` · ${goal}` : ""}`,
    prompt: `Audit my plan from ${start} until my race on ${race}${goalText}.`,
    action,
  };
}

export interface BuildPlanConfig {
  subtitle: string;
  /** Unset without a future goal race: the card opens the profile instead. */
  prompt?: string;
  action?: QuickAction;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** "30 Nov" */
function dayMonth(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function isoToLocalDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * Build Plan card config: the next block runs from its start (the active block's start date when it is
 * still ahead, else Monday of next week) to the goal race.
 */
export function buildPlanAction(
  summary: ProfileSummary | null | undefined,
  now: Date = new Date(),
): BuildPlanConfig {
  const today = localIsoDate(now);
  const race = summary?.active_date?.slice(0, 10);
  if (!race || !ISO_DATE.test(race) || race <= today) {
    return { subtitle: "Set a goal race in your Profile to build a periodized training plan" };
  }
  const blockStart = summary?.active_start_date?.slice(0, 10);
  const nextMonday = localIsoDate(addDays(now, 7 - ((now.getDay() + 6) % 7)));
  let start = blockStart && ISO_DATE.test(blockStart) && blockStart > today ? blockStart : nextMonday;
  if (start > race) start = today; // race within the week: plan from today
  const days = Math.round((isoToLocalDate(race).getTime() - isoToLocalDate(start).getTime()) / 86_400_000) + 1;
  const weeks = Math.max(1, Math.ceil(days / 7));
  const goal = summary?.active_goal?.trim();
  return {
    subtitle: `Next block: ${goal || "Goal race"} · ${dayMonth(start)} → ${dayMonth(race)} (${weeks} ${weeks === 1 ? "week" : "weeks"})`,
    prompt: `Build my training plan for ${goal || "my goal race"} from ${start} to ${race}`,
    action: { skill: "plan-builder", start_date: start, end_date: race, mode: "new" },
  };
}

interface DashboardProps {
  me: MeResponse;
  messages: ChatMessage[];
  streaming: boolean;
  onSendPrompt: (prompt: string, newConversation?: boolean, action?: QuickAction) => void;
  onViewProfile: () => void;
  onOpenTrainingPeaks: () => void;
  appliedStagedIds?: ReadonlySet<string>;
  applyingStagedId?: string | null;
  onApplyStaged?: (stagedId: string) => void;
  planApplied?: Readonly<Record<string, AppliedTrainingPlan>>;
  planApplying?: PlanApplying | null;
  planFailedIds?: ReadonlySet<string>;
  onApplyPlan?: (stagedId: string) => void;
  /** Composer text, owned by the parent so it can be cleared on New conversation. */
  draft?: string;
  onDraftChange?: (value: string) => void;
}

export function Dashboard({
  me,
  messages,
  streaming,
  onSendPrompt,
  onViewProfile,
  onOpenTrainingPeaks,
  appliedStagedIds,
  applyingStagedId,
  onApplyStaged,
  planApplied,
  planApplying,
  planFailedIds,
  onApplyPlan,
  draft,
  onDraftChange,
}: DashboardProps) {
  const [localInput, setLocalInput] = useState("");
  const input = draft ?? localInput;
  const setInput = onDraftChange ?? setLocalInput;

  const isReady = me.profile_state === "ready";
  const firstName =
    me.summary?.firstname || me.display_name.split(" ")[0] || "Runner";
  const canSend = me.tp.connected && !streaming;
  const startNewConversation = (prompt: string, action?: QuickAction) => {
    setInput("");
    onSendPrompt(prompt, true, action);
  };
  const audit = auditScheduleAction(me.summary);
  const buildPlan = buildPlanAction(me.summary);
  const handleBuildPlan = () => {
    if (buildPlan.prompt && buildPlan.action) {
      startNewConversation(buildPlan.prompt, buildPlan.action);
    } else {
      onViewProfile();
    }
  };

  const handleComposerSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || !canSend) return;
    setInput("");
    onSendPrompt(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const trimmed = input.trim();
      if (!trimmed || !canSend) return;
      setInput("");
      onSendPrompt(trimmed);
    }
  };

  const handleOnboardingClick = () => {
    if (!me.tp.connected) {
      onOpenTrainingPeaks();
      return;
    }
    startNewConversation("Let's set up my runner profile");
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 space-y-8">
      {/* Greeting & Goal Banner */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-rose-700">
              {isReady ? "Daily Coaching Hub" : "Welcome to AI Running Coach"}
            </p>
            <h1
              id="coaching-hub"
              tabIndex={-1}
              className="mt-1 font-display text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 focus:outline-none"
            >
              {isReady
                ? `${greetingForHour()}, ${firstName}`
                : `Welcome, ${firstName}`}
            </h1>
          </div>

          {isReady && me.summary && (
            <div className="flex flex-wrap items-center gap-2">
              {me.summary.active_goal && (
                <button
                  type="button"
                  onClick={onViewProfile}
                  className="inline-flex items-center gap-2 rounded-full border border-rose-300 bg-rose-100 px-3.5 py-1.5 text-sm font-semibold text-rose-950 transition hover:border-rose-400 hover:bg-rose-200/80 cursor-pointer"
                >
                  <Target className="h-3.5 w-3.5 text-rose-700" />
                  <span>{me.summary.active_goal}</span>
                  {me.summary.active_date && (
                    <span className="text-rose-800 font-medium">
                      · {formatShortDate(me.summary.active_date)}
                    </span>
                  )}
                </button>
              )}

              {me.summary.goal_type === "plan" &&
                me.summary.north_star?.goal && (
                <button
                  type="button"
                  onClick={onViewProfile}
                  className="inline-flex items-center gap-1.5 rounded-full border border-violet-300 bg-violet-100 px-3.5 py-1.5 text-sm font-semibold text-violet-950 transition hover:border-violet-400 hover:bg-violet-200/80 cursor-pointer"
                >
                  <Compass className="h-3.5 w-3.5 text-violet-700" />
                  <span>North Star: {me.summary.north_star.goal}</span>
                </button>
              )}
            </div>
          )}
        </div>
      </section>

      {/* First-Time Onboarding Box vs Existing Runner Action Grid */}
      {!isReady ? (
        <section aria-label="Onboarding">
          <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-card">
            <div
              className="border-b border-rose-200/80 px-6 py-5"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, #FFE4E6 0%, #FCE7F3 100%)",
              }}
            >
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sunset text-white shadow-sm">
                  <Sparkles className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Onboarding
                  </h2>
                  <p className="text-sm text-slate-700">
                    Link your TrainingPeaks telemetry and build your personalised
                    race plan in two minutes
                  </p>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div
                  className={`rounded-2xl border p-4 ${
                    me.tp.connected
                      ? "border-emerald-200 bg-emerald-50/40"
                      : "border-rose-200 bg-rose-50/50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold uppercase tracking-wider text-slate-600">
                      Step 1
                    </span>
                    {me.tp.connected ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 border border-emerald-200">
                        <CheckCircle2 className="h-3 w-3" /> Connected
                      </span>
                    ) : (
                      <span className="rounded-full bg-sunset px-2.5 py-0.5 text-xs font-semibold text-white">
                        Required
                      </span>
                    )}
                  </div>
                  <p className="mt-2 font-display text-base font-bold text-slate-900">
                    Connect TrainingPeaks
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    Upload your <code>Production_tpAuth</code> cookie so your
                    coach can inspect workouts, HR zones, and CTL/ATL.
                  </p>
                </div>

                <div
                  className={`rounded-2xl border p-4 ${
                    me.tp.connected
                      ? "border-rose-200 bg-rose-50/50"
                      : "border-slate-200 bg-slate-50/50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold uppercase tracking-wider text-slate-600">
                      Step 2
                    </span>
                    <span className="rounded-full bg-white px-2.5 py-0.5 text-xs font-medium text-slate-700 border border-slate-300">
                      Interactive Chat
                    </span>
                  </div>
                  <p className="mt-2 font-display text-base font-bold text-slate-900">
                    Build Runner Profile & Race Goal
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    Set your target race, stepping-stone sub-goals, injury
                    watchpoints, and shoe rotation with your AI Coach.
                  </p>
                </div>
              </div>

              <button
                type="button"
                disabled={streaming}
                onClick={handleOnboardingClick}
                className="flex w-full items-center justify-between rounded-2xl bg-sunset bg-sunset-hover px-6 py-4 text-left text-white shadow-sunset transition disabled:opacity-60 cursor-pointer"
              >
                <div>
                  <p className="font-display text-lg font-bold">
                    {me.tp.connected
                      ? "Start Onboarding Interview"
                      : "Start Onboarding — Connect TrainingPeaks"}
                  </p>
                  <p className="text-sm text-white/90 mt-0.5">
                    {me.tp.connected
                      ? "TrainingPeaks is linked! Click to launch your profile & goal setup."
                      : "Step 1 of 2 · Validate and encrypt your TrainingPeaks session."}
                  </p>
                </div>
                <ArrowRight className="h-5 w-5 shrink-0" />
              </button>
            </div>
          </div>
        </section>
      ) : (
        <section aria-label="Quick actions" className="space-y-4">
          {/* 6 White Action Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* 1. Profile */}
            <button
              type="button"
              onClick={onViewProfile}
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-slate-400 cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-800 text-white shadow-xs transition group-hover:bg-sunset">
                  <UserCheck className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Profile
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    View & edit biometrics, race goals, injuries, and shoe
                    rotation
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-slate-800 shrink-0 mt-1" />
            </button>

            {/* 2. Analyze Today's Run */}
            <button
              type="button"
              disabled={!canSend}
              onClick={() =>
                startNewConversation("Analyze today's run", {
                  skill: "workout-analysis",
                  date_str: "today",
                  sport: "run",
                })
              }
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-rose-300 disabled:opacity-55 disabled:cursor-not-allowed cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-rose-600 text-white shadow-xs transition group-hover:bg-sunset">
                  <Activity className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Analyze Today&apos;s Run
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    Deep-dive pace, HR zones, splits, aerobic decoupling &
                    execution
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-rose-600 shrink-0 mt-1" />
            </button>

            {/* 3. Check-In Report */}
            <button
              type="button"
              disabled={!canSend}
              onClick={() =>
                startNewConversation("Checking in", { skill: "check-in-report" })
              }
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-indigo-300 disabled:opacity-55 disabled:cursor-not-allowed cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-xs transition group-hover:bg-sunset">
                  <ClipboardCheck className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Check-In Report
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    14-day training load, CTL trajectory, recovery & race
                    projection
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-indigo-600 shrink-0 mt-1" />
            </button>

            {/* 4. Trend Analysis */}
            <button
              type="button"
              disabled={!canSend}
              onClick={() =>
                startNewConversation("Trend analysis for the past 6 months", {
                  skill: "trend-analysis",
                  weeks: 26,
                })
              }
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-violet-300 disabled:opacity-55 disabled:cursor-not-allowed cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-violet-600 text-white shadow-xs transition group-hover:bg-sunset">
                  <TrendingUp className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Trend Analysis
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    Last 6 months · progress, load capacity, pacing
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-violet-600 shrink-0 mt-1" />
            </button>

            {/* 5. Audit Plan (current week, or this week → race day, max 4 weeks) */}
            <button
              type="button"
              disabled={!canSend}
              onClick={() => startNewConversation(audit.prompt, audit.action)}
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-orange-300 disabled:opacity-55 disabled:cursor-not-allowed cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-orange-500 text-white shadow-xs transition group-hover:bg-sunset">
                  <CalendarCheck className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    {audit.title}
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    {audit.subtitle}
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-orange-600 shrink-0 mt-1" />
            </button>

            {/* 6. Build Plan (next block → goal race; without a future goal it opens the profile) */}
            <button
              type="button"
              disabled={buildPlan.action ? !canSend : false}
              onClick={handleBuildPlan}
              className="group flex items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-card shadow-card-hover hover:border-amber-300 disabled:opacity-55 disabled:cursor-not-allowed cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-amber-500 text-white shadow-xs transition group-hover:bg-sunset">
                  <CalendarRange className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    Build Plan
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    {buildPlan.subtitle}
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-amber-600 shrink-0 mt-1" />
            </button>
          </div>
        </section>
      )}

      {/* Conversation Feed */}
      <ChatFeed
        messages={messages}
        streaming={streaming}
        appliedStagedIds={appliedStagedIds}
        applyingStagedId={applyingStagedId}
        onApplyStaged={onApplyStaged}
        planApplied={planApplied}
        planApplying={planApplying}
        planFailedIds={planFailedIds}
        onApplyPlan={onApplyPlan}
      />

      {/* Coach Input Composer */}
      <section aria-label="Ask coach" className="space-y-2.5">
        {messages.length === 0 && (
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-sunset text-white shadow-2xs">
              <Activity className="h-3.5 w-3.5" />
            </span>
            <span className="font-display text-sm font-bold text-slate-800">
              AI Running Coach
            </span>
          </div>
        )}
        <form
          onSubmit={handleComposerSubmit}
          className="rounded-2xl border border-slate-200 bg-white p-2.5 shadow-card focus-within:border-rose-400 focus-within:ring-2 focus-within:ring-rose-400/20 transition"
        >
          <div className="flex items-end gap-2.5">
            <textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!canSend}
              placeholder={
                me.tp.connected
                  ? "Ask your running coach anything — fueling, workout adjustments, race strategy…"
                  : "Connect TrainingPeaks above to start chatting with your coach…"
              }
              className="flex-1 resize-none border-0 bg-transparent px-3 py-2 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!canSend || !input.trim()}
              aria-label="Send message"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sunset bg-sunset-hover text-white shadow-xs transition disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer"
            >
              {streaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
