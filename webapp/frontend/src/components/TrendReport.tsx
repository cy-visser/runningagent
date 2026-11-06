import { Suspense, lazy } from "react";
import { CheckCircle2, Layers, TrendingUp } from "lucide-react";
import { extractLeadingStatus, formatShortDate } from "../lib/format";
import type { TrendReportData } from "../types";
import { RichMarkdown, StatusPill } from "./RichMarkdown";

const TrendCharts = lazy(() => import("./TrendCharts"));

interface TrendReportProps {
  data: TrendReportData;
  markdown: string;
}

export function TrendReport({ data, markdown }: TrendReportProps) {
  const { outlook, levels, progress } = data;

  return (
    <div className="space-y-4">
      {/* Violet-to-Sky Hero Banner */}
      <div
        className="rounded-2xl border border-violet-200/80 p-5"
        style={{
          backgroundImage: "linear-gradient(135deg, #EDE9FE 0%, #E0F2FE 100%)",
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sunset text-white shadow-xs">
              <TrendingUp className="h-5 w-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display text-base font-bold text-slate-900">
                  Trend Analysis
                </h3>
                <span className="rounded-full bg-white/90 px-2.5 py-0.5 text-[11px] font-semibold text-violet-800 border border-violet-200">
                  Last 6 months
                </span>
              </div>
              <p className="text-xs text-slate-700 mt-0.5">
                {formatShortDate(data.window.start)} –{" "}
                {formatShortDate(data.window.end)} · {data.weeks.length} training
                weeks analysed
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {outlook.proven_km != null && (
              <StatusPill
                tone="emerald"
                label={`Proven ${outlook.proven_km} km/wk`}
              />
            )}
            <span className="rounded-full bg-white/90 px-3 py-0.5 text-xs font-semibold text-slate-800 border border-slate-200 tabular-nums">
              Peak {outlook.max_km.toFixed(1)} km
            </span>
          </div>
        </div>
      </div>

      {/* Progress Delta Cards */}
      {progress.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {progress.map((item, idx) => {
            const parsedVerdict = item.verdict
              ? extractLeadingStatus(item.verdict)
              : null;
            return (
              <div
                key={`${item.label}-${idx}`}
                className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card"
              >
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {item.label}
                </p>
                <div className="mt-1.5 flex items-baseline gap-2">
                  <span className="font-display text-xl font-bold text-slate-900 tabular-nums">
                    {item.latest || "—"}
                  </span>
                  {item.change && (
                    <span className="text-xs font-semibold text-orange-600 tabular-nums">
                      {item.arrow ? `${item.arrow} ` : ""}
                      {item.change}
                    </span>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-500">
                  <span className="tabular-nums">Start: {item.first || "—"}</span>
                  {parsedVerdict ? (
                    <StatusPill
                      tone={parsedVerdict.tone}
                      label={parsedVerdict.badgeText}
                    />
                  ) : item.verdict ? (
                    <span className="font-medium text-slate-700">
                      {item.verdict}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Lazy-Loaded 26-Week Charts */}
      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
          </div>
        }
      >
        <TrendCharts weeks={data.weeks} keyRunLabel={data.key_run_label} />
      </Suspense>

      {/* Weekly Load-Capacity Ladder */}
      {levels.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-orange-500" />
              <h4 className="font-display text-sm font-bold text-slate-900">
                Weekly Load-Capacity Ladder
              </h4>
            </div>
            {outlook.targets.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-600">
                {outlook.targets.map((t) => (
                  <span
                    key={t.target}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 font-medium tabular-nums"
                  >
                    {t.target} km:{" "}
                    <strong className="text-slate-900">
                      {t.build_weeks === 0
                        ? "Ready now"
                        : `~${t.build_weeks}w build`}
                    </strong>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2.5">
            {levels.map((lv) => {
              const pct = Math.round(lv.tolerated_share * 100);
              return (
                <div
                  key={lv.level}
                  className="grid grid-cols-12 items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-3.5 py-2.5 text-xs"
                >
                  <div className="col-span-3 sm:col-span-2 font-display font-bold text-slate-900 tabular-nums">
                    {lv.level}+ km/wk
                  </div>
                  <div className="col-span-5 sm:col-span-6">
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70">
                      <div
                        className={`h-full rounded-full transition-all ${
                          lv.proven ? "bg-sunset" : "bg-slate-400"
                        }`}
                        style={{
                          width: `${lv.weeks > 0 ? Math.max(12, pct) : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="col-span-4 flex items-center justify-end gap-2 text-right tabular-nums">
                    <span className="hidden sm:inline text-slate-500">
                      {lv.weeks}w ({ lv.streak }w streak)
                    </span>
                    {lv.proven ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 border border-emerald-200">
                        <CheckCircle2 className="h-3 w-3" /> Proven
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 border border-slate-200">
                        Next tier
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Coaching Narrative */}
      {markdown && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <RichMarkdown content={markdown} />
        </div>
      )}
    </div>
  );
}
