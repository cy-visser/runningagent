import { rem } from "../../shared/chartFont";
import type { ReactElement } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartTickDate, formatDuration } from "../../shared/format";
import type { TrendGoal, TrendNorthStar, TrendWeekPoint } from "../../shared/types";

interface GoalChartsProps {
  weeks: TrendWeekPoint[];
  goal?: TrendGoal | null;
  northStar?: TrendNorthStar | null;
  provenKm?: number | null;
}

const TOOLTIP_STYLE = {
  borderRadius: 12,
  border: "1px solid #E2E8F0",
  boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
  fontSize: rem(12),
};
const AXIS_TICK = { fontSize: rem(11), fill: "#64748B" };

function ChartCard({
  title,
  subtitle,
  legend,
  children,
}: {
  title: string;
  subtitle: string;
  legend?: { color: string; label: string; dashed?: boolean }[];
  children: ReactElement;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-display text-sm font-bold text-slate-900">{title}</h4>
          <p className="text-[0.6875rem] text-slate-500">{subtitle}</p>
        </div>
        {legend && (
          <div className="flex flex-wrap items-center gap-3 text-[0.6875rem] font-medium text-slate-600">
            {legend.map((l) => (
              <span key={l.label} className="inline-flex items-center gap-1">
                <span
                  className={`h-0.5 w-3 ${l.dashed ? "border-t-2 border-dashed" : ""}`}
                  style={l.dashed ? { borderColor: l.color } : { backgroundColor: l.color, height: 3 }}
                />
                {l.label}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/**
 * [min, max] of the finite values, padded by `pad` (fraction of the span, at least `minPad`),
 * rounded outward to multiples of `step` and never below 0 (all plotted values are non-negative).
 */
function paddedDomain(
  values: (number | null | undefined)[],
  pad = 0.08,
  minPad = 2,
  step = 5,
): [number, number] {
  const nums = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (!nums.length) return [0, step];
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const p = Math.max((hi - lo) * pad, minPad);
  return [
    Math.max(0, Math.floor((lo - p) / step) * step),
    Math.ceil((hi + p) / step) * step,
  ];
}

/** A. Weekly CTL against the goal's peak-CTL band (and the north-star band), with the required ramp. */
function FitnessVsGoalChart({ weeks, goal, northStar }: GoalChartsProps) {
  if (!goal) return null;
  const { ctl } = goal;
  const byWeek = new Map<string, { label: string; ctl?: number | null; plan?: number | null }>();
  for (const w of weeks) {
    if (w.week) byWeek.set(w.week, { label: formatChartTickDate(w.week), ctl: w.ctl ?? null });
  }
  for (const p of ctl.plan) {
    const row = byWeek.get(p.week) ?? { label: formatChartTickDate(p.week) };
    byWeek.set(p.week, { ...row, plan: p.ctl });
  }
  const data = [...byWeek.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v);
  if (!data.some((d) => d.ctl != null)) return null;
  const nsRange = northStar?.ctl_range;
  const domain = paddedDomain([
    ...data.map((d) => d.ctl),
    ...data.map((d) => d.plan),
    ...ctl.range,
    ...(nsRange ?? []),
  ]);

  const legend = [
    { color: "#7C3AED", label: "CTL" },
    { color: "#A78BFA", label: `${goal.label ?? "Goal"} band` },
    ...(nsRange ? [{ color: "#0EA5E9", label: "North-star band", dashed: true }] : []),
    ...(ctl.plan.length ? [{ color: "#94A3B8", label: "Required ramp", dashed: true }] : []),
  ];
  return (
    <ChartCard
      title="Fitness vs Goal CTL Band"
      subtitle={`Peak-CTL target ${ctl.target_peak} (range ${ctl.range[0]}–${ctl.range[1]})${
        ctl.required_ramp ? ` · needs +${ctl.required_ramp}/wk` : ""
      }`}
      legend={legend}
    >
      <ComposedChart data={data} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <YAxis domain={domain} tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        {nsRange && (
          <ReferenceArea
            y1={nsRange[0]}
            y2={nsRange[1]}
            fill="#0EA5E9"
            fillOpacity={0.07}
            stroke="#0EA5E9"
            strokeDasharray="4 4"
            strokeOpacity={0.6}
          />
        )}
        <ReferenceArea y1={ctl.range[0]} y2={ctl.range[1]} fill="#A78BFA" fillOpacity={0.18} />
        <Line
          type="monotone"
          dataKey="ctl"
          name="CTL"
          stroke="#7C3AED"
          strokeWidth={2.4}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
        <Line
          type="linear"
          dataKey="plan"
          name="Required ramp"
          stroke="#94A3B8"
          strokeWidth={2}
          strokeDasharray="5 4"
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartCard>
  );
}

/** B. Finish time implied by each week's LT2 pace vs the goal time (and north-star target). */
function ImpliedRaceTimeChart({ weeks, goal, northStar }: GoalChartsProps) {
  const data = weeks
    .filter((w) => w.week)
    .map((w) => ({
      label: formatChartTickDate(w.week),
      goal: w.implied_goal_s ?? null,
      ns: w.implied_ns_s ?? null,
    }));
  if (!goal || !data.some((d) => d.goal != null)) return null;
  const projection = goal.projection?.race_day_s ?? null;
  const goalDomain = paddedDomain([...data.map((d) => d.goal), goal.goal_s, projection], 0.08, 15, 60);
  const hasNs = !!northStar && data.some((d) => d.ns != null);
  const nsDomain = paddedDomain([...data.map((d) => d.ns), northStar?.target_s], 0.08, 60, 300);
  const lastLabel = data[data.length - 1]?.label;

  const legend = [
    { color: "#EC4899", label: `${goal.label} (implied)` },
    { color: "#F97316", label: "Goal", dashed: true },
    ...(hasNs
      ? [
          { color: "#0EA5E9", label: `${northStar?.label ?? "North star"} (implied)` },
          { color: "#0EA5E9", label: "NS target", dashed: true },
        ]
      : []),
  ];
  return (
    <ChartCard
      title="Implied Race Time"
      subtitle="Finish time implied by weekly LT2 pace (threshold proxy) · faster = up · dot = today's projection"
      legend={legend}
    >
      <ComposedChart data={data} margin={{ top: 6, right: hasNs ? 0 : 8, left: -2, bottom: 0 }}>
        <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <YAxis
          yAxisId="goal"
          reversed
          domain={goalDomain}
          tickFormatter={(v: number) => formatDuration(v)}
          tick={{ ...AXIS_TICK, fill: "#BE185D" }}
          axisLine={false}
          tickLine={false}
        />
        {hasNs && (
          <YAxis
            yAxisId="ns"
            orientation="right"
            reversed
            domain={nsDomain}
            tickFormatter={(v: number) => formatDuration(v)}
            tick={{ ...AXIS_TICK, fill: "#0369A1" }}
            axisLine={false}
            tickLine={false}
          />
        )}
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => [formatDuration(value), name]}
        />
        {goal.goal_s != null && (
          <ReferenceLine
            yAxisId="goal"
            y={goal.goal_s}
            stroke="#F97316"
            strokeDasharray="5 4"
            label={{ value: `Goal ${formatDuration(goal.goal_s)}`, position: "insideTopLeft", fontSize: rem(10), fill: "#C2410C" }}
          />
        )}
        {hasNs && northStar?.target_s != null && (
          <ReferenceLine
            yAxisId="ns"
            y={northStar.target_s}
            stroke="#0EA5E9"
            strokeDasharray="5 4"
            label={{ value: `NS ${formatDuration(northStar.target_s)}`, position: "insideBottomRight", fontSize: rem(10), fill: "#0369A1" }}
          />
        )}
        <Line
          yAxisId="goal"
          type="monotone"
          dataKey="goal"
          name={`${goal.label} implied`}
          stroke="#EC4899"
          strokeWidth={2.4}
          dot={{ r: 2.5, fill: "#EC4899" }}
          connectNulls
          isAnimationActive={false}
        />
        {hasNs && (
          <Line
            yAxisId="ns"
            type="monotone"
            dataKey="ns"
            name={`${northStar?.label ?? "North star"} implied`}
            stroke="#0EA5E9"
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        )}
        {projection != null && lastLabel && (
          <ReferenceDot
            yAxisId="goal"
            x={lastLabel}
            y={projection}
            r={5}
            fill="#F97316"
            stroke="#fff"
            strokeWidth={2}
          />
        )}
      </ComposedChart>
    </ChartCard>
  );
}

/** C. Sub-goal targets / results and today's projection as north-star equivalents vs the north-star target. */
function NorthStarMilestonesChart({ northStar }: GoalChartsProps) {
  if (!northStar || !northStar.milestones.length) return null;
  const data = [
    ...northStar.milestones.map((m) => ({
      label: m.training_goal,
      target: m.target_equiv_s ?? null,
      result: m.result_equiv_s ?? null,
      now: null as number | null,
    })),
    ...(northStar.equivalent_s
      ? [{ label: "Now (projection)", target: null, result: null, now: northStar.equivalent_s }]
      : []),
  ];
  const domain = paddedDomain(
    [...data.flatMap((d) => [d.target, d.result, d.now]), northStar.target_s],
    0.08,
    60,
    60,
  );
  return (
    <ChartCard
      title="North-Star Milestones"
      subtitle={`Sub goals as ${northStar.label ?? "north-star"} equivalents (Riegel) vs ${northStar.training_goal} · faster = up`}
      legend={[
        { color: "#94A3B8", label: "Target equiv." },
        { color: "#10B981", label: "Result equiv." },
        { color: "#F97316", label: "Now" },
        { color: "#0EA5E9", label: "North star", dashed: true },
      ]}
    >
      <ComposedChart data={data} margin={{ top: 6, right: 8, left: -2, bottom: 0 }}>
        <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <YAxis
          reversed
          domain={domain}
          tickFormatter={(v: number) => formatDuration(v)}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => [formatDuration(value), name]}
        />
        {northStar.target_s != null && (
          <ReferenceLine
            y={northStar.target_s}
            stroke="#0EA5E9"
            strokeDasharray="5 4"
            label={{ value: `North star ${formatDuration(northStar.target_s)}`, position: "insideTopRight", fontSize: rem(10), fill: "#0369A1" }}
          />
        )}
        <Line
          type="linear"
          dataKey="target"
          name="Target equiv."
          stroke="#94A3B8"
          strokeDasharray="4 4"
          dot={{ r: 4, fill: "#94A3B8" }}
          connectNulls
          isAnimationActive={false}
        />
        <Line
          type="linear"
          dataKey="result"
          name="Result equiv."
          stroke="#10B981"
          strokeWidth={2}
          dot={{ r: 5, fill: "#10B981" }}
          connectNulls
          isAnimationActive={false}
        />
        <Line
          type="linear"
          dataKey="now"
          name="Now (projection)"
          stroke="#F97316"
          dot={{ r: 6, fill: "#F97316", stroke: "#fff", strokeWidth: 2 }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartCard>
  );
}

interface ReadinessPoint {
  label: string;
  long_km?: number | null;
  km?: number | null;
}

/** Historical weeks ordered chronologically for the long-run & weekly-volume readiness chart. */
export function readinessData(weeks: TrendWeekPoint[]): ReadinessPoint[] {
  const byWeek = new Map<string, ReadinessPoint>();
  for (const w of weeks) {
    if (w.week) byWeek.set(w.week, { label: formatChartTickDate(w.week), long_km: w.long_km, km: w.km });
  }
  return [...byWeek.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v);
}

/** "Longest run per week · proven 70 km/wk". */
export function readinessSubtitle(provenKm?: number | null): string {
  const parts = ["Longest run per week"];
  if (provenKm) {
    parts.push(`proven ${provenKm} km/wk`);
  }
  return parts.join(" · ");
}

/** D. Weekly long run and weekly km against proven historical capacity (facts only, no synthetic target path). */
function LongRunReadinessChart({ weeks, goal, provenKm }: GoalChartsProps) {
  if (!goal?.label) return null;
  const data = readinessData(weeks);
  if (!data.some((d) => (d.long_km ?? 0) > 0)) return null;
  const longDomain = paddedDomain([...data.map((d) => d.long_km), 0]);
  const kmDomain = paddedDomain(
    [...data.map((d) => d.km), provenKm, 0],
    0.08,
    2,
    10,
  );
  return (
    <ChartCard
      title="Long-Run & Volume Readiness"
      subtitle={readinessSubtitle(provenKm)}
      legend={[
        { color: "#F97316", label: "Longest run" },
        { color: "#7C3AED", label: "km/wk" },
        ...(provenKm ? [{ color: "#7C3AED", label: "Proven", dashed: true }] : []),
      ]}
    >
      <ComposedChart data={data} margin={{ top: 6, right: 0, left: -18, bottom: 0 }}>
        <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <YAxis yAxisId="long" domain={longDomain} tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <YAxis
          yAxisId="km"
          orientation="right"
          domain={kmDomain}
          tick={{ ...AXIS_TICK, fill: "#7C3AED" }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value: number, name: string) => [`${value} km`, name]} />
        {provenKm ? (
          <ReferenceLine yAxisId="km" y={provenKm} stroke="#7C3AED" strokeDasharray="5 4" strokeOpacity={0.7} />
        ) : null}
        <Bar
          yAxisId="long"
          dataKey="long_km"
          name="Longest run"
          fill="#F97316"
          radius={[6, 6, 2, 2]}
          maxBarSize={22}
          isAnimationActive={false}
        />
        <Line
          yAxisId="km"
          type="monotone"
          dataKey="km"
          name="Weekly km"
          stroke="#7C3AED"
          strokeWidth={2}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartCard>
  );
}

export default function GoalCharts(props: GoalChartsProps) {
  const charts = [
    <FitnessVsGoalChart key="fitness" {...props} />,
    <ImpliedRaceTimeChart key="implied" {...props} />,
    <NorthStarMilestonesChart key="milestones" {...props} />,
    <LongRunReadinessChart key="longrun" {...props} />,
  ];
  return <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">{charts}</div>;
}
