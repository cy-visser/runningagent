import { rem } from "../../shared/chartFont";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartTickDate, formatDuration } from "../../shared/format";
import type { TrendWeekPoint } from "../../shared/types";

interface DynamicsChartsProps {
  weeks: TrendWeekPoint[];
  refPaceS?: number | null;
}

export default function DynamicsCharts({ weeks, refPaceS }: DynamicsChartsProps) {
  const chartData = weeks.map((w) => ({
    ...w,
    label: formatChartTickDate(w.week),
  }));

  const hasEfficiency = chartData.some(
    (d) => d.rd_gct_ms != null || d.rd_vert_ratio_pct != null,
  );
  const hasCadStride = chartData.some(
    (d) => d.rd_cadence != null || d.rd_stride_m != null,
  );

  if (!hasEfficiency && !hasCadStride) return null;

  const refLabel = refPaceS != null ? `@ ${formatDuration(refPaceS)}/km · ` : "";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Chart 1: Pace-normalized Running Form Efficiency (GCT + Vertical Ratio, lower = better) */}
      {hasEfficiency && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h4 className="font-display text-base font-bold text-slate-900">
                Running Form Efficiency
              </h4>
              <p className="text-xs text-slate-500">
                {refLabel}rolling 4-wk pace-normalized · lower = up
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs font-medium text-slate-600 shrink-0">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-orange-500" /> GCT
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-violet-600" /> Vert Ratio
              </span>
            </div>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 6, right: 8, left: -12, bottom: 0 }}
              >
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
                  yAxisId="gct"
                  reversed
                  domain={["dataMin - 4", "dataMax + 4"]}
                  tickFormatter={(v: number) => `${Math.round(v)}`}
                  tick={{ fontSize: rem(13), fill: "#F97316" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="vr"
                  orientation="right"
                  reversed
                  domain={["dataMin - 0.3", "dataMax + 0.3"]}
                  tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                  tick={{ fontSize: rem(13), fill: "#7C3AED" }}
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
                  formatter={(value: number, name: string): [string, string] =>
                    name === "GCT"
                      ? [`${value.toFixed(1)} ms`, "GCT"]
                      : [`${value.toFixed(2)}%`, "Vert Ratio"]
                  }
                  labelFormatter={(label: string, payload) => {
                    const row = payload?.[0]?.payload as TrendWeekPoint | undefined;
                    const extras: string[] = [];
                    if (row?.rd_vert_osc_cm != null) {
                      extras.push(`Vert Osc ${row.rd_vert_osc_cm.toFixed(1)} cm`);
                    }
                    if (row?.rd_fade_checked && row.rd_fade_checked > 0) {
                      extras.push(
                        `Fade ${row.rd_fade_runs ?? 0}/${row.rd_fade_checked}`,
                      );
                    }
                    return extras.length ? `${label} · ${extras.join(" · ")}` : label;
                  }}
                />
                <Line
                  yAxisId="gct"
                  type="monotone"
                  dataKey="rd_gct_ms"
                  name="GCT"
                  stroke="#F97316"
                  strokeWidth={2.4}
                  dot={{ r: 2.5, fill: "#F97316" }}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  yAxisId="vr"
                  type="monotone"
                  dataKey="rd_vert_ratio_pct"
                  name="Vert Ratio"
                  stroke="#7C3AED"
                  strokeWidth={2.4}
                  dot={{ r: 2.5, fill: "#7C3AED" }}
                  connectNulls
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Chart 2: Pace-normalized Cadence & Stride Length */}
      {hasCadStride && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h4 className="font-display text-base font-bold text-slate-900">
                Cadence &amp; Stride Length
              </h4>
              <p className="text-xs text-slate-500">
                {refLabel}rolling 4-wk pace-normalized
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs font-medium text-slate-600 shrink-0">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-sky-500" /> Cadence
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-pink-500" /> Stride
              </span>
            </div>
          </div>

          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 6, right: 8, left: -12, bottom: 0 }}
              >
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
                  yAxisId="cad"
                  domain={["dataMin - 3", "dataMax + 3"]}
                  tickFormatter={(v: number) => `${Math.round(v)}`}
                  tick={{ fontSize: rem(13), fill: "#0EA5E9" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="sl"
                  orientation="right"
                  domain={[
                    (d: number) => Number((d - 0.04).toFixed(2)),
                    (d: number) => Number((d + 0.04).toFixed(2)),
                  ]}
                  tickFormatter={(v: number) => `${v.toFixed(2)}m`}
                  tick={{ fontSize: rem(13), fill: "#EC4899" }}
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
                  formatter={(value: number, name: string) =>
                    name === "Cadence"
                      ? [`${value.toFixed(1)} spm`, "Cadence"]
                      : [`${value.toFixed(2)} m`, "Stride"]
                  }
                />
                <Line
                  yAxisId="cad"
                  type="monotone"
                  dataKey="rd_cadence"
                  name="Cadence"
                  stroke="#0EA5E9"
                  strokeWidth={2.4}
                  dot={{ r: 2.5, fill: "#0EA5E9" }}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  yAxisId="sl"
                  type="monotone"
                  dataKey="rd_stride_m"
                  name="Stride"
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
