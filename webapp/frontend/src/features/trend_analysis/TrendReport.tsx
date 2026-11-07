import { Suspense, lazy } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Compass,
  Gauge,
  Layers,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { extractLeadingStatus, formatDuration, formatShortDate } from "../../shared/format";
import type { StatusPillTone } from "../../shared/format";
import type {
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

      {/* Coach Recommendations (the only LLM-written text) */}
      {markdown && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <RichMarkdown content={markdown} />
        </div>
      )}
    </div>
  );
}
