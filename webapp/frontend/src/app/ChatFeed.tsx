import { useEffect, useRef } from "react";
import { Activity, AlertCircle } from "lucide-react";
import type { ChatMessage } from "../shared/types";
import { AuditReport } from "../features/schedule_audit/AuditReport";
import { CheckinReport } from "../features/check_in_report/CheckinReport";
import { RichMarkdown } from "../shared/RichMarkdown";
import { ToolProgress } from "./ToolProgress";
import { TrendReport } from "../features/trend_analysis/TrendReport";

interface ChatFeedProps {
  messages: ChatMessage[];
}

export function ChatFeed({ messages }: ChatFeedProps) {
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
          </div>
        );
      })}
    </section>
  );
}
