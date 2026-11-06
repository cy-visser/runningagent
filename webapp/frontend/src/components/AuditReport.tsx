import { Suspense, lazy } from "react";
import { CalendarCheck } from "lucide-react";
import { formatShortDate } from "../lib/format";
import type { AuditReportData } from "../types";
import { RichMarkdown, StatusPill } from "./RichMarkdown";

const AuditCharts = lazy(() => import("./AuditCharts"));

interface AuditReportProps {
  data: AuditReportData;
  markdown: string;
}

export function AuditReport({ data, markdown }: AuditReportProps) {
  const totalKm = data.weeks.reduce((acc, w) => acc + w.km, 0);
  const totalQuality = data.weeks.reduce((acc, w) => acc + w.quality, 0);
  const totalEasy = data.weeks.reduce((acc, w) => acc + w.easy, 0);

  return (
    <div className="space-y-4">
      {/* Hero Banner */}
      <div
        className="rounded-2xl border border-orange-200/80 p-5"
        style={{
          backgroundImage: "linear-gradient(135deg, #FFF7ED 0%, #FDF2F8 100%)",
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sunset text-white shadow-xs">
              <CalendarCheck className="h-5 w-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display text-base font-bold text-slate-900">
                  Schedule Audit
                </h3>
                <span className="rounded-full bg-white/90 px-2.5 py-0.5 text-[11px] font-semibold text-orange-800 border border-orange-200">
                  {data.weeks.length}{" "}
                  {data.weeks.length === 1 ? "week" : "weeks"}
                </span>
              </div>
              <p className="text-xs text-slate-700 mt-0.5">
                {formatShortDate(data.window.start)} –{" "}
                {formatShortDate(data.window.end)}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <StatusPill
              tone="slate"
              label={`${totalEasy} easy · ${totalQuality} quality`}
            />
            <span className="rounded-full bg-white/90 px-3 py-0.5 text-xs font-semibold text-slate-800 border border-slate-200 tabular-nums">
              {totalKm.toFixed(1)} km total
            </span>
          </div>
        </div>
      </div>

      {/* Stacked-bar weekly chart */}
      <Suspense
        fallback={
          <div className="h-80 rounded-2xl border border-slate-200 animate-shimmer" />
        }
      >
        <AuditCharts weeks={data.weeks} />
      </Suspense>

      {/* Coaching Evaluation */}
      {markdown && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <RichMarkdown content={markdown} />
        </div>
      )}
    </div>
  );
}
