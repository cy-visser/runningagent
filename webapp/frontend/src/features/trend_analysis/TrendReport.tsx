import { Suspense, lazy } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Compass,
  Footprints,
  Gauge,
  Layers,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { extractLeadingStatus, formatDuration, formatShortDate } from "../../shared/format";
import type { StatusPillTone } from "../../shared/format";
import type {
  TrendDynamicsSummary,
  TrendGoal,
  TrendLevelItem,
  TrendNorthStar,
  TrendPaceRow,
  TrendReportData,
  TrendTargetItem,
} from "../../shared/types";
import { RichMarkdown, StatusBadge, StatusPill, directionFromArrow } from "../../shared/RichMarkdown";

const TrendCharts = lazy(() => import("./TrendCharts"));
const GoalCharts = lazy(() => import("./GoalCharts"));
const DynamicsCharts = lazy(() => import("./DynamicsCharts"));

const LEVEL_STEP_KM = 10;

interface TrendReportProps {
  data: TrendReportData;
  markdown: string;
}

/** Gap pill: ahead / on target = emerald, within 2% of the target = amber, further behind = rose. */
function gapPill(gapS: number | null | undefined, targetS: number | null | undefined) {
  if (gapS == null) return null;
  const tone: StatusPillTone =
    gapS <= 0 ? "emerald" : targetS && gapS / targetS <= 0.02 ? "amber" : "rose";
  const label =
    Math.abs(gapS) < 1
      ? "On target"
      : gapS < 0
        ? `${formatDuration(-gapS)} ahead`
        : `+${formatDuration(gapS)} behind`;
  return { tone, label };
}

/** Target chip: proven / ready = check, within reach = alert, untested / far = dashed circle. */
function targetBadge(t: TrendTargetItem): { tone: StatusPillTone; icon: LucideIcon } {
  const status = (t.status ?? "").toLowerCase();
  if (status === "proven" || (!status && t.gap_km <= 0)) {
    return { tone: "emerald", icon: CheckCircle2 };
  }
  if (status === "within reach") return { tone: "amber", icon: AlertTriangle };
  return { tone: "slate", icon: CircleDashed };
}

/**
 * Highest proven level plus the next tier (grey). Lower proven levels are implied and hidden.
 * Nothing proven yet: only the lowest level that was run.
 */
export function ladderLevels(levels: TrendLevelItem[]): TrendLevelItem[] {
  if (!levels.length) return [];
  const proven = levels.filter((l) => l.proven);
  if (!proven.length) return [levels[0]];
  const top = proven.reduce((a, b) => (b.level > a.level ? b : a));
  const nextLevel = top.level + LEVEL_STEP_KM;
  const next = levels.find((l) => l.level === nextLevel) ?? {
    level: nextLevel,
    weeks: 0,
    streak: 0,
    tolerated_share: 0,
    proven: false,
  };
  return [top, next];
}

function GoalProjectionCard({ goal }: { goal: TrendGoal }) {
  const p = goal.projection;
  const gap = gapPill(p?.gap_s, goal.goal_s);
  return (
    <div className="min-w-[13.75rem] rounded-xl border border-white/80 bg-white/85 px-3.5 py-2.5 shadow-2xs">
      <div className="flex items-center gap-1.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
        <Target className="h-3.5 w-3.5 text-orange-500" />
        Goal{goal.weeks_to_race != null ? ` · ${Math.round(goal.weeks_to_race)} wk` : ""}
      </div>
      <p className="text-xs font-semibold text-slate-800">{goal.training_goal}</p>
      {p?.race_day_s ? (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="font-display text-lg font-bold text-slate-900 tabular-nums">
            {formatDuration(p.race_day_s)}
          </span>
          {gap && <StatusPill tone={gap.tone} label={gap.label} />}
          {p.confidence && (
            <span className="text-[0.6875rem] text-slate-500">
              {p.confidence} confidence{p.stale ? " · stale" : ""}
            </span>
          )}
        </div>
      ) : (
        <p className="mt-1 text-[0.6875rem] text-slate-500">Projection: insufficient recent data</p>
      )}
    </div>
  );
}

function NorthStarCard({ ns }: { ns: TrendNorthStar }) {
  const gap = gapPill(ns.gap_s, ns.target_s);
  return (
    <div className="min-w-[13.75rem] rounded-xl border border-white/80 bg-white/85 px-3.5 py-2.5 shadow-2xs">
      <div className="flex items-center gap-1.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
        <Compass className="h-3.5 w-3.5 text-sky-600" />
        North star{ns.weeks_to_race != null ? ` · ${Math.round(ns.weeks_to_race)} wk` : ""}
      </div>
      <p className="text-xs font-semibold text-slate-800">{ns.training_goal}</p>
      {ns.equivalent_s ? (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="font-display text-lg font-bold text-slate-900 tabular-nums">
            ≈ {formatDuration(ns.equivalent_s)}
          </span>
          {gap && <StatusPill tone={gap.tone} label={gap.label} />}
        </div>
      ) : (
        <p className="mt-1 text-[0.6875rem] text-slate-500">No projection to map yet</p>
      )}
    </div>
  );
}

function PacesTable({ paces }: { paces: TrendPaceRow[] }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
      <div className="mb-3 flex items-center gap-2">
        <Gauge className="h-4 w-4 text-orange-500" />
        <h4 className="font-display text-sm font-bold text-slate-900">Training Paces</h4>
        <span className="text-[0.6875rem] text-slate-500">threshold estimate + HR model, last 6 weeks</span>
      </div>
      <table className="w-full text-xs">
        <tbody>
          {paces.map((p) => (
            <tr key={p.name} className="border-t border-slate-100 first:border-t-0">
              <td className="py-2 pr-3 font-medium text-slate-700">{p.name}</td>
              <td className="py-2 text-right font-display font-bold text-slate-900 tabular-nums">
                {p.pace}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunningMechanicsCard({ dynamics }: { dynamics: TrendDynamicsSummary }) {
  const bands = dynamics.bands ?? [];
  const sm = dynamics.speed_modulation;
  const fade = dynamics.late_fade;
  if (bands.length === 0 && (!fade || fade.checked === 0)) return null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Footprints className="h-4 w-4 text-orange-500" />
          <h4 className="font-display text-sm font-bold text-slate-900">
            Running Mechanics &amp; Late-Run Durability
          </h4>
          {bands.length > 0 && (
            <span className="text-[0.6875rem] text-slate-500">
              by pace band (last 6 weeks)
            </span>
          )}
        </div>
        {fade && fade.checked > 0 && (
          <StatusBadge
            tone={fade.faded > 0 ? "amber" : "emerald"}
            icon={fade.faded > 0 ? AlertTriangle : CheckCircle2}
            size="sm"
            label={
              fade.faded > 0
                ? `${fade.faded}/${fade.checked} runs late-run fade`
                : `Form held (${fade.checked}/${fade.checked} runs)`
            }
          />
        )}
      </div>

      {bands.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-[0.6875rem] uppercase tracking-wider text-slate-500">
                <th className="py-1.5 pr-3 font-semibold">Band</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Min</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Pace</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Cadence</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Stride</th>
                <th className="py-1.5 pr-3 font-semibold text-right">GCT</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Vert Osc</th>
                <th className="py-1.5 font-semibold text-right">Vert Ratio</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {bands.map((b) => (
                <tr key={b.band}>
                  <td className="py-2 pr-3 font-semibold text-slate-900 whitespace-nowrap">
                    {b.band}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-500">{b.minutes}</td>
                  <td className="py-2 pr-3 text-right font-medium text-slate-800 whitespace-nowrap">
                    {formatDuration(b.pace_s)}/km
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-700 whitespace-nowrap">
                    {b.cadence != null ? `${b.cadence.toFixed(0)} spm` : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-700 whitespace-nowrap">
                    {b.stride_m != null ? `${b.stride_m.toFixed(2)} m` : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-700 whitespace-nowrap">
                    {b.gct_ms != null ? `${b.gct_ms.toFixed(0)} ms` : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-700 whitespace-nowrap">
                    {b.vert_osc_cm != null ? `${b.vert_osc_cm.toFixed(1)} cm` : "—"}
                  </td>
                  <td className="py-2 text-right font-semibold text-slate-900 whitespace-nowrap">
                    {b.vert_ratio_pct != null ? `${b.vert_ratio_pct.toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sm && (
        <div className="rounded-xl border border-slate-100 bg-slate-50/70 px-3.5 py-2 text-xs text-slate-700 tabular-nums">
          <span className="font-semibold text-slate-900">
            Speed modulation ({sm.from_band} → {sm.to_band}, +{sm.speed_gain_pct.toFixed(1)}%):
          </span>{" "}
          {sm.cadence_share_pct}% cadence ({sm.cadence_from.toFixed(0)}→{sm.cadence_to.toFixed(0)} spm) ·{" "}
          {sm.stride_share_pct}% stride ({sm.stride_from_m.toFixed(2)}→{sm.stride_to_m.toFixed(2)} m)
        </div>
      )}

      {fade && fade.checked > 0 && (
        <div className="border-t border-slate-100 pt-2.5 text-xs text-slate-600 space-y-1 tabular-nums">
          <p>
            <span className="font-semibold text-slate-800">Late-run durability:</span>{" "}
            {fade.faded} of {fade.checked} runs flagged
            {fade.median_gct_delta_ms != null
              ? ` · median GCT ${fade.median_gct_delta_ms > 0 ? "+" : ""}${fade.median_gct_delta_ms.toFixed(0)} ms`
              : ""}
            {fade.median_vr_delta_pp != null
              ? ` · median VR ${fade.median_vr_delta_pp > 0 ? "+" : ""}${fade.median_vr_delta_pp.toFixed(2)} pp`
              : ""}
          </p>
          {fade.flagged_runs.slice(0, 3).map((r, i) => {
            const parts: string[] = [];
            if (r.gct_delta_ms != null) parts.push(`GCT ${r.gct_delta_ms > 0 ? "+" : ""}${r.gct_delta_ms.toFixed(0)} ms`);
            if (r.vr_delta_pp != null) parts.push(`VR ${r.vr_delta_pp > 0 ? "+" : ""}${r.vr_delta_pp.toFixed(2)} pp`);
            if (r.cadence_delta != null) parts.push(`Cad ${r.cadence_delta > 0 ? "+" : ""}${r.cadence_delta.toFixed(0)} spm`);
            if (r.stride_delta_pct != null) parts.push(`SL ${r.stride_delta_pct > 0 ? "+" : ""}${r.stride_delta_pct.toFixed(1)}%`);
            return (
              <p key={`${r.date}-${i}`}>
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

export function TrendReport({ data, markdown }: TrendReportProps) {
  const { outlook, levels, progress } = data;
  const ladder = ladderLevels(levels);

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
                <span className="rounded-full bg-white/90 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-violet-800 border border-violet-200">
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

          {/* Projection toward the goal and the north star */}
          {(data.goal?.training_goal || data.north_star) && (
            <div className="flex flex-wrap items-stretch gap-2">
              {data.goal?.training_goal && <GoalProjectionCard goal={data.goal} />}
              {data.north_star && <NorthStarCard ns={data.north_star} />}
            </div>
          )}
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
                <p className="text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
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
                <div className="mt-2 flex items-center justify-between gap-2 text-[0.6875rem] text-slate-500">
                  <span className="tabular-nums">Start: {item.first || "—"}</span>
                  {parsedVerdict ? (
                    <StatusBadge
                      tone={parsedVerdict.tone}
                      label={parsedVerdict.badgeText}
                      size="sm"
                      direction={directionFromArrow(item.arrow)}
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

      {/* Lazy-Loaded Trend + Goal-Progress Charts */}
      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
            <div className="h-64 rounded-2xl border border-slate-200 animate-shimmer" />
          </div>
        }
      >
        <div className="space-y-4">
          <TrendCharts weeks={data.weeks} keyRunLabel={data.key_run_label} />
          <GoalCharts
            weeks={data.weeks}
            goal={data.goal}
            northStar={data.north_star}
            provenKm={outlook.proven_km}
          />
          <DynamicsCharts
            weeks={data.weeks}
            refPaceS={data.dynamics?.ref_pace_s}
          />
        </div>
      </Suspense>

      {/* Weekly Load-Capacity Ladder: highest proven level + next tier */}
      {ladder.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-orange-500" />
              <h4 className="font-display text-sm font-bold text-slate-900">
                Weekly Load-Capacity Ladder
              </h4>
            </div>
            {outlook.targets.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-[0.6875rem] text-slate-600">
                {outlook.targets.map((t) => {
                  const badge = targetBadge(t);
                  return (
                    <StatusBadge
                      key={t.target}
                      tone={badge.tone}
                      icon={badge.icon}
                      size="sm"
                      className="tabular-nums"
                      label={`${t.target} km: ${
                        t.gap_km <= 0 ? "Ready now" : `+${Math.round(t.gap_km)} km to go`
                      }`}
                    />
                  );
                })}
              </div>
            )}
          </div>

          <div className="space-y-2.5">
            {ladder.map((lv) => {
              const pct = Math.round(lv.tolerated_share * 100);
              return (
                <div
                  key={lv.level}
                  data-testid="ladder-row"
                  className={`grid grid-cols-12 items-center gap-3 rounded-xl border px-3.5 py-2.5 text-xs ${
                    lv.proven
                      ? "border-slate-100 bg-slate-50/50"
                      : "border-slate-100 bg-slate-50/30 text-slate-400"
                  }`}
                >
                  <div
                    className={`col-span-3 sm:col-span-2 font-display font-bold tabular-nums ${
                      lv.proven ? "text-slate-900" : "text-slate-400"
                    }`}
                  >
                    {lv.level}+ km/wk
                  </div>
                  <div className="col-span-5 sm:col-span-6">
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70">
                      <div
                        className={`h-full rounded-full transition-all ${
                          lv.proven ? "bg-sunset" : "bg-slate-300"
                        }`}
                        style={{
                          width: `${lv.weeks > 0 ? Math.max(12, pct) : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="col-span-4 flex items-center justify-end gap-2 text-right tabular-nums">
                    <span className="hidden sm:inline text-slate-500">
                      {lv.weeks > 0 ? `${lv.weeks}w (${lv.streak}w streak)` : "not run yet"}
                    </span>
                    {lv.proven ? (
                      <StatusBadge tone="emerald" icon="check" label="Proven" size="sm" />
                    ) : (
                      <StatusBadge tone="slate" icon={CircleDashed} label="Next tier" size="sm" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Training Paces */}
      {data.paces && data.paces.length > 0 && <PacesTable paces={data.paces} />}

      {/* Running Mechanics & Late-Run Durability */}
      {data.dynamics && <RunningMechanicsCard dynamics={data.dynamics} />}

      {/* Coach Recommendations (the only LLM-written text) */}
      {markdown && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <RichMarkdown content={markdown} />
        </div>
      )}
    </div>
  );
}
