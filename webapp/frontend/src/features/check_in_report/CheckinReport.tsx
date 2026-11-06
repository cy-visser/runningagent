import { Suspense, lazy } from "react";
import { Activity, Flame, Gauge, HeartPulse, Timer } from "lucide-react";
import {
  formatDuration,
  formatShortDate,
  formatSignedGap,
  splitMarkdownSections,
} from "../../shared/format";
import type {
  CheckinDriver,
  CheckinLtPaces,
  CheckinReportData,
} from "../../shared/types";
import { CollapsibleSection } from "./CollapsibleSection";
import { RichMarkdown, StatusPill } from "../../shared/RichMarkdown";

const CheckinCharts = lazy(() => import("./CheckinCharts"));

interface CheckinReportProps {
  data: CheckinReportData;
  markdown: string;
}

function CtlProgressRing({ percent }: { percent: number }) {
  const clamped = Math.min(100, Math.max(0, percent));
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (clamped / 100) * circumference;

  return (
    <div className="relative flex h-16 w-16 shrink-0 items-center justify-center">
      <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64">
        <defs>
          <linearGradient id="ctlRingSunset" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#F97316" />
            <stop offset="100%" stopColor="#EC4899" />
          </linearGradient>
        </defs>
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke="#F1F5F9"
          strokeWidth="6"
        />
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke="url(#ctlRingSunset)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
        />
      </svg>
      <span className="absolute font-display text-sm font-bold text-slate-900 tabular-nums">
        {clamped}%
      </span>
    </div>
  );
}

/** Signed s/km change vs the previous 4 weeks; faster (negative) is good. */
function PaceDelta({ now, prev }: { now?: number | null; prev?: number | null }) {
  if (now == null || prev == null) {
    return <span className="text-xs text-slate-400">no prior 4-wk fit</span>;
  }
  const delta = Math.round(now - prev);
  const stable = Math.abs(delta / prev) < 0.01;
  const tone = stable ? "text-slate-500" : delta < 0 ? "text-emerald-600" : "text-rose-600";
  return (
    <span className={`text-xs font-semibold tabular-nums ${tone}`}>
      {delta > 0 ? `+${delta}` : delta} s/km
    </span>
  );
}

function ThresholdPacesCard({ lt }: { lt: CheckinLtPaces }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Threshold Paces
        </p>
        <Gauge className="h-4 w-4 text-pink-500" />
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
          {lt.lt2_pace_s != null ? `${formatDuration(lt.lt2_pace_s)}/km` : "—"}
        </span>
        <span className="text-sm font-medium text-slate-500">
          LT2{lt.lthr != null ? ` · ${lt.lthr} bpm` : ""}
          {lt.lt2_extrapolated ? " ⚠️" : ""}
        </span>
      </div>
      <div className="mt-0.5">
        <PaceDelta now={lt.lt2_pace_s} prev={lt.lt2_prev_s} />
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-sm text-slate-600 tabular-nums">
        <span>
          LT1{" "}
          <strong className="text-slate-900">
            {lt.lt1_pace_s != null ? `${formatDuration(lt.lt1_pace_s)}/km` : "—"}
          </strong>
          {lt.lt1_hr != null ? ` · ${lt.lt1_hr} bpm` : ""}
          {lt.lt1_extrapolated ? " ⚠️" : ""}
        </span>
        <PaceDelta now={lt.lt1_pace_s} prev={lt.lt1_prev_s} />
      </div>
    </div>
  );
}

/** Evidence behind the race projection (rendered from the payload, never typed by the coach). */
function ProjectionDrivers({ drivers }: { drivers: CheckinDriver[] }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        Projection Drivers
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wider text-slate-500">
              <th className="py-1.5 pr-3 font-semibold">Driver</th>
              <th className="py-1.5 pr-3 font-semibold">Evidence</th>
              <th className="py-1.5 font-semibold">Implied pace / effect</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {drivers.map((d) => (
              <tr key={d.driver}>
                <td className="py-1.5 pr-3 font-semibold text-slate-900 whitespace-nowrap">
                  {d.driver}
                </td>
                <td className="py-1.5 pr-3 text-slate-600">{d.evidence}</td>
                <td className="py-1.5 text-slate-700 tabular-nums whitespace-nowrap">
                  {d.implied}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function CheckinReport({ data, markdown }: CheckinReportProps) {
  const { ctl, projection, recovery, lt } = data;

  const rampBadge =
    ctl.ramp_tier === "safe"
      ? { tone: "emerald" as const, label: "Safe Ramp" }
      : ctl.ramp_tier === "aggressive"
        ? { tone: "amber" as const, label: "Aggressive Ramp" }
        : ctl.ramp_tier === "high_risk"
          ? { tone: "rose" as const, label: "High-Risk Ramp" }
          : { tone: "slate" as const, label: ctl.phase ? `${ctl.phase} phase` : "Active Block" };

  const gapInfo = formatSignedGap(projection?.gap_s);
  const gapTone =
    gapInfo.tone === "positive"
      ? ("emerald" as const)
      : gapInfo.tone === "warning"
        ? ("amber" as const)
        : gapInfo.tone === "danger"
          ? ("rose" as const)
          : ("slate" as const);

  return (
    <div className="space-y-4">
      {/* Peach-to-Blush Hero Banner */}
      <div
        className="rounded-2xl border border-orange-200/80 p-5"
        style={{
          backgroundImage: "linear-gradient(135deg, #FFEDD5 0%, #FCE7F3 100%)",
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sunset text-white shadow-xs">
              <Activity className="h-5 w-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display text-lg font-bold text-slate-900">
                  14-Day Coaching Check-In
                </h3>
                {ctl.phase && (
                  <span className="rounded-full bg-white/85 px-2.5 py-0.5 text-xs font-semibold capitalize text-orange-800 border border-orange-200">
                    {ctl.phase}
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-700 mt-0.5">
                {formatShortDate(data.window.start)} –{" "}
                {formatShortDate(data.window.end)}
                {ctl.weeks_remaining != null
                  ? ` · ${ctl.weeks_remaining} weeks to race day`
                  : ""}
              </p>
            </div>
          </div>

          <StatusPill tone={rampBadge.tone} label={rampBadge.label} />
        </div>
      </div>

      {/* KPI Cards (4 with threshold paces) */}
      <div
        className={`grid grid-cols-1 gap-4 ${lt ? "md:grid-cols-2 xl:grid-cols-4" : "md:grid-cols-3"}`}
      >
        {/* Card 1: CTL Ring */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Chronic Load (CTL)
            </p>
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
                {ctl.current.toFixed(1)}
              </span>
              <span className="text-sm font-medium text-slate-500 tabular-nums">
                / {ctl.target.toFixed(0)} target
              </span>
            </div>
            <p className="mt-1.5 text-sm text-slate-500 tabular-nums">
              {ctl.required_ramp != null
                ? `Req. +${ctl.required_ramp.toFixed(2)} CTL/wk`
                : `Ref range ${ctl.range[0]}–${ctl.range[1]}`}
            </p>
          </div>
          <CtlProgressRing percent={ctl.pct} />
        </div>

        {/* Card 2: Threshold paces (LT1 / LT2) */}
        {lt && <ThresholdPacesCard lt={lt} />}

        {/* Card 3: Race Projection */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Race Projection
            </p>
            <Timer className="h-4 w-4 text-orange-500" />
          </div>
          {projection?.race_day_s != null ? (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
                  {formatDuration(projection.race_day_s)}
                </span>
                {projection.goal_s != null && (
                  <span className="text-sm text-slate-500 tabular-nums">
                    goal {formatDuration(projection.goal_s)}
                  </span>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusPill tone={gapTone} label={gapInfo.label} />
                {projection.today_s != null && (
                  <span className="text-xs text-slate-500 tabular-nums">
                    Today eq. {formatDuration(projection.today_s)}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="mt-2">
              <p className="font-display text-base font-bold text-slate-800">
                {projection?.goal_label || "Building Race Estimate"}
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Log a threshold or benchmark effort to unlock time projection.
              </p>
            </div>
          )}
        </div>

        {/* Card 4: Fatigue & Recovery */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Form & Recovery
            </p>
            {recovery ? (
              <HeartPulse className="h-4 w-4 text-pink-500" />
            ) : (
              <Flame className="h-4 w-4 text-orange-500" />
            )}
          </div>
          <div className="mt-1 flex items-baseline gap-3">
            <div>
              <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
                {ctl.tsb > 0 ? `+${ctl.tsb.toFixed(1)}` : ctl.tsb.toFixed(1)}
              </span>
              <span className="ml-1 text-sm font-medium text-slate-500">
                TSB
              </span>
            </div>
            <span className="text-sm text-slate-500 tabular-nums">
              ATL {ctl.atl.toFixed(1)}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-600 tabular-nums">
            {recovery?.hrv_latest != null && (
              <span>
                HRV <strong className="text-slate-900">{recovery.hrv_latest} ms</strong>
              </span>
            )}
            {recovery?.rhr_latest != null && (
              <span>
                RHR <strong className="text-slate-900">{recovery.rhr_latest} bpm</strong>
              </span>
            )}
            {recovery?.sleep_avg_h != null && (
              <span>
                Sleep <strong className="text-slate-900">{recovery.sleep_avg_h}h</strong>
              </span>
            )}
            {!recovery && (
              <span className="text-slate-400">
                Wearable recovery metrics optional
              </span>
            )}
          </div>
        </div>
      </div>

      {projection?.drivers && projection.drivers.length > 0 && (
        <ProjectionDrivers drivers={projection.drivers} />
      )}

      {/* Lazy-Loaded Charts */}
      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
          </div>
        }
      >
        <CheckinCharts pmc={data.pmc} weeks={data.weeks} />
      </Suspense>

      {/* Coaching Narrative: analysis sections collapsed, overview & priorities always visible */}
      {markdown && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-3">
          {splitMarkdownSections(markdown).map((section, idx) =>
            section.collapsible ? (
              <CollapsibleSection
                key={`sec-${idx}-${section.title}`}
                title={section.title}
                body={section.body}
              />
            ) : (
              <div key={`sec-${idx}-${section.title}`}>
                {section.title && (
                  <h3 className="font-display text-base font-bold text-slate-900 mb-1.5">
                    {section.title}
                  </h3>
                )}
                {section.body && <RichMarkdown content={section.body} />}
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}
