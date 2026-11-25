import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { rem } from "../../shared/chartFont";
import { formatChartTickDate, formatDuration, formatShortDate } from "../../shared/format";
import type {
  YearReviewMonthPoint,
  YearReviewRacePin,
  YearReviewWeekPoint,
} from "../../shared/types";

interface YearReviewChartProps {
  year?: number;
  monthly: YearReviewMonthPoint[];
  weekly: YearReviewWeekPoint[];
}

interface ChartRow {
  label: string;
  km: number;
  ctl: number | null;
  ctlPeakDate: string | null;
  runs: number;
  partial: boolean;
  future: boolean;
  races: YearReviewRacePin[];
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: ChartRow }>;
  granularity: "monthly" | "weekly";
}

function TrajectoryTooltip({ active, payload, granularity }: CustomTooltipProps) {
  const row = payload?.[0]?.payload;
  if (!active || !row || row.future) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs shadow-lg space-y-1.5 tabular-nums">
      <div className="flex items-center justify-between gap-4 font-display font-bold text-slate-900">
        <span>
          {row.label}
          {row.partial ? " (in progress)" : ""}
        </span>
        <span className="text-slate-500 font-sans font-medium">
          {row.runs} run{row.runs === 1 ? "" : "s"}
        </span>
      </div>
      <div className="flex items-center gap-4 text-slate-700">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-orange-500" />
          <strong className="text-slate-900">{row.km.toFixed(1)} km</strong>{" "}
          {granularity === "monthly" ? "/ mo" : "/ wk"}
        </span>
        {row.ctl != null && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-violet-600" />
            Peak CTL <strong className="text-slate-900">{row.ctl.toFixed(1)}</strong>
            {row.ctlPeakDate ? (
              <span className="text-slate-500">
                ({formatShortDate(row.ctlPeakDate).replace(/, \d{4}$/, "")})
              </span>
            ) : null}
          </span>
        )}
      </div>
      {row.races.length > 0 && (
        <div className="border-t border-slate-100 pt-1.5 space-y-1">
          {row.races.map((r) => (
            <div key={`${r.date}-${r.name}`} className="flex items-center justify-between gap-3">
              <span className="font-semibold text-amber-800">
                {r.is_pr ? "★ " : "• "}
                {r.name}
              </span>
              {r.duration_s != null && (
                <span className="font-display font-bold text-slate-900">
                  {formatDuration(r.duration_s)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function YearReviewChart({ year, monthly, weekly }: YearReviewChartProps) {
  const [granularity, setGranularity] = useState<"monthly" | "weekly">("monthly");

  const rows: ChartRow[] =
    granularity === "monthly"
      ? monthly.map((m) => ({
          label: m.partial ? `${m.label}*` : m.label,
          km: m.future ? 0 : m.km,
          ctl: m.future ? null : (m.ctl ?? null),
          ctlPeakDate: m.future ? null : (m.ctl_peak_date ?? null),
          runs: m.runs,
          partial: m.partial,
          future: Boolean(m.future),
          races: m.races ?? [],
        }))
      : weekly.map((w) => ({
          label: formatChartTickDate(w.week),
          km: w.km,
          ctl: w.ctl ?? null,
          ctlPeakDate: w.ctl_peak_date ?? null,
          runs: w.runs,
          partial: w.partial,
          future: false,
          races: w.races ?? [],
        }));

  if (rows.length === 0) return null;

  const hasCtl = rows.some((r) => r.ctl != null);
  const raceDots = rows.filter((r) => r.races.length > 0 && r.ctl != null);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-bold text-slate-900">
            {year ? `${year} ` : ""}Running Volume &amp; Fitness Trajectory
          </h3>
          <p className="text-xs text-slate-500">
            {granularity === "monthly" ? "Monthly" : "Weekly"} running km (Jan – Dec) vs Peak Chronic Training Load (CTL) with main races pinned
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-3 text-xs font-medium text-slate-600">
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-orange-500" />
              {granularity === "monthly" ? "km / mo" : "km / wk"}
            </span>
            {hasCtl && (
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-violet-600" /> Peak CTL
              </span>
            )}
            {raceDots.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-amber-500 ring-1 ring-amber-600" /> Race
              </span>
            )}
          </div>

          <div
            role="group"
            aria-label="Chart granularity"
            className="inline-flex rounded-xl bg-slate-100 p-0.5 text-xs font-semibold"
          >
            <button
              type="button"
              onClick={() => setGranularity("monthly")}
              aria-pressed={granularity === "monthly"}
              className={`rounded-lg px-2.5 py-1 transition cursor-pointer ${
                granularity === "monthly"
                  ? "bg-white text-slate-900 shadow-2xs"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Monthly
            </button>
            <button
              type="button"
              onClick={() => setGranularity("weekly")}
              aria-pressed={granularity === "weekly"}
              className={`rounded-lg px-2.5 py-1 transition cursor-pointer ${
                granularity === "weekly"
                  ? "bg-white text-slate-900 shadow-2xs"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Weekly
            </button>
          </div>
        </div>
      </div>

      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 14, right: hasCtl ? 6 : 8, left: -14, bottom: 0 }}
          >
            <defs>
              <linearGradient id="yearReviewKmGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#F97316" stopOpacity={0.92} />
                <stop offset="100%" stopColor="#EC4899" stopOpacity={0.82} />
              </linearGradient>
              <linearGradient id="yearReviewKmPartialGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#F97316" stopOpacity={0.48} />
                <stop offset="100%" stopColor="#EC4899" stopOpacity={0.4} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: rem(11), fill: "#64748B" }}
              axisLine={false}
              tickLine={false}
              interval={granularity === "weekly" ? 5 : 0}
            />
            <YAxis
              yAxisId="km"
              tick={{ fontSize: rem(11), fill: "#64748B" }}
              axisLine={false}
              tickLine={false}
            />
            {hasCtl && (
              <YAxis
                yAxisId="ctl"
                orientation="right"
                tick={{ fontSize: rem(11), fill: "#7C3AED" }}
                axisLine={false}
                tickLine={false}
                domain={["dataMin - 6", "dataMax + 6"]}
              />
            )}
            <Tooltip content={<TrajectoryTooltip granularity={granularity} />} />
            <Bar
              yAxisId="km"
              dataKey="km"
              name="Running km"
              radius={[6, 6, 2, 2]}
              maxBarSize={granularity === "monthly" ? 36 : 12}
              isAnimationActive={false}
            >
              {rows.map((entry, idx) => (
                <Cell
                  key={`${entry.label}-${idx}`}
                  fill={entry.partial ? "url(#yearReviewKmPartialGrad)" : "url(#yearReviewKmGrad)"}
                  stroke={entry.partial ? "#F97316" : undefined}
                  strokeDasharray={entry.partial ? "3 2" : undefined}
                />
              ))}
            </Bar>
            {hasCtl && (
              <Line
                yAxisId="ctl"
                type="monotone"
                dataKey="ctl"
                name="CTL"
                stroke="#7C3AED"
                strokeWidth={2.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            )}
            {raceDots.map((row) => {
              const primary = row.races[0];
              return (
                <ReferenceDot
                  key={`race-${row.label}-${primary.date}`}
                  yAxisId="ctl"
                  x={row.label}
                  y={row.ctl!}
                  r={5.5}
                  fill={primary.is_pr ? "#F59E0B" : "#7C3AED"}
                  stroke="#FFFFFF"
                  strokeWidth={2}
                  label={{
                    value: `${primary.short_label}${primary.is_pr ? " ★" : ""}`,
                    position: "top",
                    fontSize: rem(10),
                    fontWeight: 700,
                    fill: primary.is_pr ? "#B45309" : "#5B21B6",
                    offset: 7,
                  }}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
