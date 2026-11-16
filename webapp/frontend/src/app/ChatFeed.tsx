import { useEffect, useRef } from "react";
import { Activity, AlertCircle } from "lucide-react";
import type { AppliedTrainingPlan, ChatMessage } from "../shared/types";
import { AuditReport } from "../features/plan_audit/AuditReport";
import { CheckinReport } from "../features/check_in_report/CheckinReport";
import {
  PlanStagedCard,
  type PlanStatus,
} from "../features/plan_builder/PlanStagedCard";
import {
  StagedChangesCard,
  type StagedStatus,
} from "../features/workout_creator/StagedChangesCard";
import { RichMarkdown } from "../shared/RichMarkdown";
import { ToolProgress } from "./ToolProgress";
import { TrendReport } from "../features/trend_analysis/TrendReport";
import { WorkoutReport } from "../features/workout_analysis/WorkoutReport";

/** Week-by-week plan apply in progress (driven by App's apply loop). */
export interface PlanApplying {
  stagedId: string;
  week: number;
}

interface ChatFeedProps {
  messages: ChatMessage[];
  streaming?: boolean;
  appliedStagedIds?: ReadonlySet<string>;
  applyingStagedId?: string | null;
  onApplyStaged?: (stagedId: string) => void;
  /** Latest `applied_training_plan` per staged plan id. */
  planApplied?: Readonly<Record<string, AppliedTrainingPlan>>;
  planApplying?: PlanApplying | null;
  /** Plans whose apply loop stopped on a stream error (Resume). */
  planFailedIds?: ReadonlySet<string>;
  onApplyPlan?: (stagedId: string) => void;
}

export function ChatFeed({
  messages,
  streaming = false,
  appliedStagedIds,
  applyingStagedId = null,
  onApplyStaged,
  planApplied,
  planApplying = null,
  planFailedIds,
  onApplyPlan,
}: ChatFeedProps) {
  const latestTurnRef = useRef<HTMLDivElement | null>(null);
  const mountedCountRef = useRef<number | null>(null);

  useEffect(() => {
    if (mountedCountRef.current === null) {
      mountedCountRef.current = messages.length;
      return;
    }
    if (messages.length > mountedCountRef.current) {
      mountedCountRef.current = messages.length;
      latestTurnRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [messages.length]);

  if (messages.length === 0) {
    return null;
  }

  // Only the most recent staged set can be applied; older cards show "Replaced".
  const latestStagedId = [...messages].reverse().find((m) => m.staged)?.staged?.staged_id;
  const stagedStatus = (stagedId: string): StagedStatus => {
    if (appliedStagedIds?.has(stagedId)) return "applied";
    if (stagedId !== latestStagedId) return "replaced";
    if (streaming && applyingStagedId === stagedId) return "applying";
    return "pending";
  };

  // Same for staged plans: a newer plan replaces older, not fully applied ones.
  const latestPlanId = [...messages].reverse().find((m) => m.plan)?.plan?.staged_id;
  const planStatus = (stagedId: string): PlanStatus => {
    const applied = planApplied?.[stagedId];
    if (applied?.done) return "applied";
    if (stagedId !== latestPlanId) return "replaced";
    if (planApplying?.stagedId === stagedId) return "applying";
    if (applied || planFailedIds?.has(stagedId)) return "partial";
    return "pending";
  };

  return (
    <section
      id="coaching-feed"
      aria-label="Coaching conversation"
      className="space-y-5"
    >
      {messages.map((msg, idx) => {
        const isLast = idx === messages.length - 1;
        if (msg.role === "user") {
          return (
            <div
              key={msg.id}
              ref={isLast ? latestTurnRef : undefined}
              className="flex justify-end scroll-mt-20"
            >
              <div className="max-w-2xl rounded-2xl rounded-br-sm bg-slate-900 px-4 py-3 text-base font-medium text-white shadow-xs">
                {msg.text}
              </div>
            </div>
          );
        }

        const checkinData =
          msg.report?.kind === "checkin" ? msg.report.data : null;
        const trendData = msg.report?.kind === "trend" ? msg.report.data : null;
        const auditData = msg.report?.kind === "audit" ? msg.report.data : null;
        const workoutData = msg.report?.kind === "workout" ? msg.report.data : null;

        return (
          <div
            key={msg.id}
            ref={isLast ? latestTurnRef : undefined}
            className="space-y-2.5 scroll-mt-20"
          >
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-sunset text-white shadow-2xs">
                <Activity className="h-3.5 w-3.5" />
              </span>
              <span className="font-display text-sm font-bold text-slate-800">
                AI Running Coach
              </span>
              {msg.streaming && (
                <span className="text-xs font-medium text-orange-600 animate-pulse">
                  Running…
                </span>
              )}
            </div>

            <ToolProgress thinking={msg.thinking} tools={msg.tools} />

            {msg.error && (
              <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
                <span>{msg.error}</span>
              </div>
            )}

            {checkinData ? (
              <CheckinReport data={checkinData} markdown={msg.text} />
            ) : trendData ? (
              <TrendReport data={trendData} markdown={msg.text} />
            ) : auditData ? (
              <AuditReport data={auditData} markdown={msg.text} />
            ) : workoutData ? (
              <WorkoutReport data={workoutData} markdown={msg.text} />
            ) : msg.text ? (
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
                <RichMarkdown content={msg.text} />
              </div>
            ) : msg.streaming && !msg.error ? (
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card animate-shimmer">
                <div className="h-3 w-48 rounded-full bg-orange-200/60 mb-2.5" />
                <div className="h-2.5 w-full rounded-full bg-slate-200/70 mb-2" />
                <div className="h-2.5 w-3/4 rounded-full bg-slate-200/70" />
              </div>
            ) : null}

            {msg.staged && onApplyStaged && (
              <StagedChangesCard
                staged={msg.staged}
                status={stagedStatus(msg.staged.staged_id)}
                busy={streaming}
                onApply={onApplyStaged}
              />
            )}

            {msg.plan && onApplyPlan && (
              <PlanStagedCard
                plan={msg.plan}
                status={planStatus(msg.plan.staged_id)}
                applied={planApplied?.[msg.plan.staged_id] ?? null}
                applyingWeek={
                  planApplying?.stagedId === msg.plan.staged_id ? planApplying.week : null
                }
                busy={streaming || planApplying !== null}
                onApply={onApplyPlan}
              />
            )}

            {!msg.streaming && msg.usage && <TokenStatsBadge usage={msg.usage} />}
          </div>
        );
      })}
    </section>
  );
}

function fmtTokens(n: number): string {
  return n.toLocaleString("en-US");
}

function TokenStatsBadge({ usage }: { usage: NonNullable<ChatMessage["usage"]> }) {
  const steps =
    usage.steps && usage.steps.length > 0
      ? usage.steps
      : [
          {
            input_tokens: usage.input_tokens,
            cached_tokens: usage.cached_tokens,
            output_tokens: usage.output_tokens,
          },
        ];

  return (
    <div className="px-1">
      <span
        tabIndex={0}
        className="group relative inline-flex items-center text-[11px] leading-tight text-slate-400 underline decoration-dotted decoration-slate-300 underline-offset-3 transition-colors hover:text-slate-600 focus-visible:text-slate-600 focus-visible:outline-none cursor-default"
      >
        Tokens
        <span
          role="tooltip"
          className="pointer-events-none invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 focus:visible transition-opacity duration-100 absolute bottom-full left-0 mb-1.5 sm:bottom-auto sm:left-full sm:top-1/2 sm:-translate-y-1/2 sm:mb-0 sm:ml-2.5 z-30 flex flex-col gap-0.5 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[11px] leading-snug text-slate-50 shadow-lg tabular-nums whitespace-nowrap"
        >
          {steps.map((step, i) => (
            <span key={i}>
              Call {i + 1}: {fmtTokens(step.input_tokens)} in ·{" "}
              {fmtTokens(step.cached_tokens)} cached ·{" "}
              {fmtTokens(step.output_tokens)} out
            </span>
          ))}
          {steps.length > 1 && (
            <span className="mt-0.5 border-t border-slate-700/80 pt-0.5 text-slate-300">
              Total: {fmtTokens(usage.input_tokens)} in ·{" "}
              {fmtTokens(usage.cached_tokens)} cached ·{" "}
              {fmtTokens(usage.output_tokens)} out
            </span>
          )}
        </span>
      </span>
    </div>
  );
}
