import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartTickDate, formatDuration } from "../../shared/format";
import type { TrendWeekPoint } from "../../shared/types";

interface TrendChartsProps {
  weeks: TrendWeekPoint[];
  keyRunLabel?: string | null;
}

export default function TrendCharts({ weeks, keyRunLabel }: TrendChartsProps) {
  const chartData = weeks.map((w) => ({
    ...w,
    label: formatChartTickDate(w.week),
  }));

  if (chartData.length === 0) return null;

  const hasLtPaces = chartData.some(
    (d) => d.lt1_pace_s != null || d.lt2_pace_s != null,
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Chart 1: 26-Week Volume + CTL */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h4 className="font-display text-sm font-bold text-slate-900">
              6-Month Weekly Volume & CTL
            </h4>
            <p className="text-[11px] text-slate-500">
              Weekly mileage (Sunset bars) vs Chronic Training Load
            </p>
          </div>
          <div className="flex items-center gap-3 text-[11px] font-medium text-slate-600">
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-orange-500" /> km/wk
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-violet-600" /> CTL
            </span>
          </div>
        </div>

        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartData}
              margin={{ top: 6, right: 8, left: -18, bottom: 0 }}
            >
              <defs>
                <linearGradient id="trendKmGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F97316" stopOpacity={0.92} />
                  <stop offset="100%" stopColor="#EC4899" stopOpacity={0.85} />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="#F1F5F9"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#64748B" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                yAxisId="km"
                tick={{ fontSize: 11, fill: "#64748B" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                yAxisId="ctl"
                orientation="right"
                tick={{ fontSize: 11, fill: "#7C3AED" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  border: "1px solid #E2E8F0",
                  boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
                  fontSize: 12,
                }}
              />
              <Bar
                yAxisId="km"
                dataKey="km"
                name="Weekly km"
                fill="url(#trendKmGrad)"
                radius={[6, 6, 2, 2]}
                maxBarSize={26}
                isAnimationActive={false}
              />
              <Line
                yAxisId="ctl"
                type="monotone"
                dataKey="ctl"
                name="CTL"
                stroke="#7C3AED"
                strokeWidth={2.4}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart 2: Threshold paces (LT1 / LT2) */}
      {hasLtPaces && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h4 className="font-display text-sm font-bold text-slate-900">
                Threshold Paces (LT1 / LT2)
              </h4>
              <p className="text-[11px] text-slate-500">
                Pace at top of zone 2 &amp; at LTHR · rolling 4-week fit · faster = up
              </p>
            </div>
            <div className="flex items-center gap-3 text-[11px] font-medium text-slate-600">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-sky-500" /> LT1
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-pink-500" /> LT2
              </span>
            </div>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 6, right: 8, left: -6, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="#F1F5F9"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  reversed
                  domain={["dataMin - 5", "dataMax + 5"]}
                  tickFormatter={(v: number) => formatDuration(v)}
                  tick={{ fontSize: 11, fill: "#64748B" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 12,
                    border: "1px solid #E2E8F0",
                    boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
                    fontSize: 12,
                  }}
                  formatter={(value: number, name: string, props) => {
                    const row = props?.payload as TrendWeekPoint | undefined;
                    const flag = name === "LT2" && row?.lt2_extrapolated ? " (extrapolated)" : "";
                    return [`${formatDuration(value)}/km${flag}`, name];
                  }}
                  labelFormatter={(label: string, payload) => {
                    const row = payload?.[0]?.payload as TrendWeekPoint | undefined;
                    return row?.key_decoupling != null
                      ? `${label} · Key-run Pa:Hr ${row.key_decoupling}%${keyRunLabel ? ` (${keyRunLabel})` : ""}`
                      : label;
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="lt1_pace_s"
                  name="LT1"
                  stroke="#0EA5E9"
                  strokeWidth={2.4}
                  dot={{ r: 2.5, fill: "#0EA5E9" }}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="lt2_pace_s"
                  name="LT2"
                  stroke="#EC4899"
                  strokeWidth={2.4}
                  dot={{ r: 2.5, fill: "#EC4899" }}
                  connectNulls
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
