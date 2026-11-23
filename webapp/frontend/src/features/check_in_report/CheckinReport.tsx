import { Suspense, lazy } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Flame,
  Footprints,
  Gauge,
  HeartPulse,
  Info,
  Timer,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import {
  extractLeadingStatus,
  formatDuration,
  formatShortDate,
  formatSignedGap,
  splitMarkdownSections,
} from "../../shared/format";
import type {
  CheckinDriver,
  CheckinLtPaces,
  CheckinReportData,
  CheckinRunningDynamics,
} from "../../shared/types";
import { CollapsibleSection } from "./CollapsibleSection";
import { RichMarkdown, StatusBadge } from "../../shared/RichMarkdown";

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

function DynamicsDelta({
  now,
  prev,
  unit,
  digits = 0,
  threshold,
}: {
  now?: number | null;
  prev?: number | null;
  unit: string;
  digits?: number;
  threshold: number;
}) {
  if (now == null || prev == null) return null;
  const delta = now - prev;
  const stable = Math.abs(delta) < threshold;
  const tone = stable ? "text-slate-500" : delta < 0 ? "text-emerald-600" : "text-rose-600";
  const sign = delta > 0 ? "+" : "";
  return (
    <span className={`text-xs font-semibold tabular-nums ${tone}`}>
      {sign}
      {delta.toFixed(digits)} {unit} vs prior 4 wk
    </span>
  );
}

function RunningDynamicsCard({ dynamics }: { dynamics: CheckinRunningDynamics }) {
  const hasMetrics =
    dynamics.gct_ms != null ||
    dynamics.vert_ratio_pct != null ||
    dynamics.cadence_spm != null ||
    dynamics.stride_m != null ||
    dynamics.vert_osc_cm != null;
  const fade = dynamics.late_fade;
  if (!hasMetrics && (!fade || fade.checked === 0)) return null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Footprints className="h-4 w-4 text-orange-500" />
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Running Form &amp; Dynamics
          </p>
          {dynamics.ref_pace_s != null && (
            <span className="text-xs text-slate-400 tabular-nums">
              @ {formatDuration(dynamics.ref_pace_s)}/km (4 wk)
            </span>
          )}
        </div>
        {fade && fade.checked > 0 && (
          <StatusBadge
            tone={fade.faded > 0 ? "amber" : "emerald"}
            icon={fade.faded > 0 ? AlertTriangle : CheckCircle2}
            label={
              fade.faded > 0
                ? `${fade.faded}/${fade.checked} runs late-run fade`
                : `Form held (${fade.checked}/${fade.checked} runs)`
            }
            size="sm"
          />
        )}
      </div>

      {hasMetrics && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {dynamics.gct_ms != null && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Ground Contact
              </p>
              <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                {dynamics.gct_ms.toFixed(0)} <span className="text-xs font-medium text-slate-500">ms</span>
              </p>
              <DynamicsDelta now={dynamics.gct_ms} prev={dynamics.gct_prev_ms} unit="ms" digits={0} threshold={3} />
            </div>
          )}
          {dynamics.vert_ratio_pct != null && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Vert Ratio
              </p>
              <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                {dynamics.vert_ratio_pct.toFixed(1)}
                <span className="text-xs font-medium text-slate-500">%</span>
              </p>
              <DynamicsDelta
                now={dynamics.vert_ratio_pct}
                prev={dynamics.vert_ratio_prev_pct}
                unit="pp"
                digits={2}
                threshold={0.2}
              />
            </div>
          )}
          {dynamics.cadence_spm != null && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Cadence
              </p>
              <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                {dynamics.cadence_spm.toFixed(0)} <span className="text-xs font-medium text-slate-500">spm</span>
              </p>
            </div>
          )}
          {dynamics.stride_m != null && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Stride Length
              </p>
              <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                {dynamics.stride_m.toFixed(2)} <span className="text-xs font-medium text-slate-500">m</span>
              </p>
            </div>
          )}
          {dynamics.vert_osc_cm != null && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Vert Osc
              </p>
              <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                {dynamics.vert_osc_cm.toFixed(1)} <span className="text-xs font-medium text-slate-500">cm</span>
              </p>
            </div>
          )}
        </div>
      )}

      {fade && fade.flagged_runs.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-600 space-y-1">
          {fade.flagged_runs.map((r, i) => {
            const parts: string[] = [];
            if (r.gct_delta_ms != null) parts.push(`GCT ${r.gct_delta_ms > 0 ? "+" : ""}${r.gct_delta_ms.toFixed(0)} ms`);
            if (r.vr_delta_pp != null) parts.push(`VR ${r.vr_delta_pp > 0 ? "+" : ""}${r.vr_delta_pp.toFixed(2)} pp`);
            if (r.cadence_delta != null) parts.push(`Cad ${r.cadence_delta > 0 ? "+" : ""}${r.cadence_delta.toFixed(0)} spm`);
            if (r.stride_delta_pct != null) parts.push(`SL ${r.stride_delta_pct > 0 ? "+" : ""}${r.stride_delta_pct.toFixed(1)}%`);
            return (
              <p key={`${r.date}-${i}`} className="tabular-nums">
                <span className="font-semibold text-amber-700">{r.date ? formatShortDate(r.date) : "Run"}</span>{" "}
                · {r.title} ({r.scope}): {parts.join(", ")}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Leading status emoji in a driver cell ("🟢 readiness") renders as a small badge. */
function ImpliedCell({ text }: { text: string }) {
  const status = text ? extractLeadingStatus(text) : null;
  if (!status || status.restText) return <>{text}</>;
  return <StatusBadge tone={status.tone} icon={status.icon} label={status.badgeText} size="sm" />;
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
                  <ImpliedCell text={d.implied} />
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
  const { ctl, projection, recovery, lt, dynamics } = data;

  const rampBadge =
    ctl.ramp_tier === "safe"
      ? { tone: "emerald" as const, label: "Safe Ramp", icon: TrendingUp }
      : ctl.ramp_tier === "aggressive"
        ? { tone: "amber" as const, label: "Aggressive Ramp", icon: AlertTriangle }
        : ctl.ramp_tier === "high_risk"
          ? { tone: "rose" as const, label: "High-Risk Ramp", icon: XCircle }
          : {
              tone: "slate" as const,
              label: ctl.phase ? `${ctl.phase} phase` : "Active Block",
              icon: Info,
            };

  const gapInfo = formatSignedGap(projection?.gap_s);
  const gapTone =
    gapInfo.tone === "positive"
      ? ("emerald" as const)
      : gapInfo.tone === "warning"
        ? ("amber" as const)
        : gapInfo.tone === "danger"
          ? ("rose" as const)
          : ("slate" as const);
  // Ahead / on goal = check; behind = trending down (amber) or x (rose).
  const gapIcon =
    gapTone === "emerald"
      ? CheckCircle2
      : gapTone === "amber"
        ? TrendingDown
        : gapTone === "rose"
          ? XCircle
          : Info;

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

          <StatusBadge tone={rampBadge.tone} label={rampBadge.label} icon={rampBadge.icon} />
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
                <StatusBadge tone={gapTone} label={gapInfo.label} icon={gapIcon} />
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

      {dynamics && <RunningDynamicsCard dynamics={dynamics} />}

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
