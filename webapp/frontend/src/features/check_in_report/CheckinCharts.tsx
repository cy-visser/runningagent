import { rem } from "../../shared/chartFont";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartTickDate } from "../../shared/format";
import type { CheckinPmcPoint, CheckinWeekItem } from "../../shared/types";

interface CheckinChartsProps {
  pmc: CheckinPmcPoint[];
  weeks: CheckinWeekItem[];
}

export default function CheckinCharts({ pmc, weeks }: CheckinChartsProps) {
  const pmcData = pmc.map((pt) => ({
    ...pt,
    label: formatChartTickDate(pt.date),
  }));

  const weekData = weeks.map((w) => ({
    ...w,
    label: w.date_range
      ? w.date_range.split("–")[0].trim()
      : formatChartTickDate(w.week),
  }));

  if (pmcData.length === 0 && weekData.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {pmcData.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h4 className="font-display text-base font-bold text-slate-900">
                Fitness · Fatigue · Form (PMC)
              </h4>
              <p className="text-xs text-slate-500">
                90-day CTL progression vs acute load & freshness
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs font-medium text-slate-600">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-orange-500" /> CTL
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-pink-500" /> ATL
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-indigo-500" /> TSB
              </span>
            </div>
          </div>

          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={pmcData}
                margin={{ top: 6, right: 8, left: -18, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="ctlAreaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#F97316" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#EC4899" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  stroke="#F1F5F9"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: rem(13), fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: rem(13), fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 12,
                    border: "1px solid #E2E8F0",
                    boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
                    fontSize: rem(14),
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="ctl"
                  name="CTL (Fitness)"
                  stroke="#F97316"
                  strokeWidth={2.5}
                  fill="url(#ctlAreaGrad)"
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="atl"
                  name="ATL (Fatigue)"
                  stroke="#EC4899"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="tsb"
                  name="TSB (Form)"
                  stroke="#6366F1"
                  strokeWidth={1.75}
                  strokeDasharray="4 4"
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {weekData.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h4 className="font-display text-base font-bold text-slate-900">
                Weekly Distance & Session Mix
              </h4>
              <p className="text-xs text-slate-500">
                Recent weekly volume (km) · dashed bar = current week in progress
              </p>
            </div>
            <span className="rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-semibold text-orange-700 border border-orange-200/70">
              km / wk
            </span>
          </div>

          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={weekData}
                margin={{ top: 6, right: 8, left: -18, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="sunsetBar" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#F97316" />
                    <stop offset="100%" stopColor="#EC4899" />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  stroke="#F1F5F9"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: rem(13), fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: rem(13), fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: "#FFF7ED" }}
                  contentStyle={{
                    borderRadius: 12,
                    border: "1px solid #E2E8F0",
                    boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
                    fontSize: rem(14),
                  }}
                  formatter={(value: number, _name: string, props) => {
                    const row = props?.payload as CheckinWeekItem | undefined;
                    const suffix = row?.in_progress
                      ? " km (in progress)"
                      : row?.partial
                        ? " km (partial week)"
                        : " km";
                    const detail = row
                      ? ` · ${row.tss} TSS (${row.easy} easy / ${row.quality} quality)`
                      : "";
                    return [`${value}${suffix}${detail}`, "Volume"];
                  }}
                />
                <Bar
                  dataKey="km"
                  radius={[8, 8, 2, 2]}
                  maxBarSize={44}
                  isAnimationActive={false}
                >
                  {weekData.map((entry, idx) => (
                    <Cell
                      key={`wk-${idx}`}
                      fill={entry.partial ? "#FED7AA" : "url(#sunsetBar)"}
                      stroke={entry.partial ? "#F97316" : "none"}
                      strokeDasharray={entry.partial ? "4 3" : undefined}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
