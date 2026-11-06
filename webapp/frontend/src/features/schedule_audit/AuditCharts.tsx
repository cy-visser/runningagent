import { useId, useState } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartTickDate } from "../../shared/format";
import type {
  AuditSession,
  AuditSessionCategory,
  AuditWeek,
} from "../../shared/types";

interface AuditChartsProps {
  weeks: AuditWeek[];
}

const CATEGORY_META: Record<
  AuditSessionCategory,
  { label: string; color: string; dotClass: string }
> = {
  easy: {
    label: "Easy run",
    color: "#38BDF8",
    dotClass: "bg-sky-400",
  },
  quality: {
    label: "Quality run",
    color: "#F97316",
    dotClass: "bg-orange-500",
  },
  bike: {
    label: "Bike",
    color: "#8B5CF6",
    dotClass: "bg-violet-500",
  },
  strength: {
    label: "Strength",
    color: "#10B981",
    dotClass: "bg-emerald-500",
  },
  other: {
    label: "Other",
    color: "#94A3B8",
    dotClass: "bg-slate-400",
  },
};

const DEFAULT_XT_MINUTES = 30;

function formatDayShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const clean = iso.slice(0, 10);
  const parts = clean.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return clean;
  const [y, m, d] = parts;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function isRun(s: AuditSession): boolean {
  return s.category === "easy" || s.category === "quality";
}

interface HoveredSegment {
  weekIdx: number;
  session: AuditSession;
}

interface ChartRow {
  label: string;
  week: AuditWeek;
  runs: AuditSession[];
  xts: AuditSession[];
  [key: string]: unknown;
}

export default function AuditCharts({ weeks }: AuditChartsProps) {
  const uid = useId().replace(/:/g, "");
  const [hovered, setHovered] = useState<HoveredSegment | null>(null);

  if (weeks.length === 0) return null;

  let maxRuns = 0;
  let maxXts = 0;

  const rows: ChartRow[] = weeks.map((w) => {
    const runs = w.sessions.filter(isRun);
    const xts = w.sessions.filter((s) => !isRun(s));
    if (runs.length > maxRuns) maxRuns = runs.length;
    if (xts.length > maxXts) maxXts = xts.length;

    const row: ChartRow = {
      label: formatChartTickDate(w.week) || w.date_range || "",
      week: w,
      runs,
      xts,
    };
    runs.forEach((r, idx) => {
      row[`run_${idx}`] = r.km;
    });
    xts.forEach((x, idx) => {
      row[`xt_${idx}`] = x.minutes > 0 ? x.minutes : DEFAULT_XT_MINUTES;
    });
    return row;
  });

  const runIndices = Array.from({ length: maxRuns }, (_, i) => i);
  const xtIndices = Array.from({ length: maxXts }, (_, i) => i);
  const hasXt = maxXts > 0;

  const patternId = (cat: AuditSessionCategory) => `hatch-${uid}-${cat}`;
  const fillFor = (s: AuditSession | undefined): string => {
    if (!s) return "transparent";
    const meta = CATEGORY_META[s.category] || CATEGORY_META.other;
    return s.completed ? meta.color : `url(#${patternId(s.category)})`;
  };
  const strokeFor = (s: AuditSession | undefined): string => {
    if (!s) return "transparent";
    return "#FFFFFF";
  };

  const annotatedWeeks = weeks.filter(
    (w) => w.long_run || (w.notes && w.notes.length > 0),
  );

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="font-display text-sm font-bold text-slate-900">
            Weekly Breakdown · Runs &amp; Cross-Training
          </h4>
          <p className="text-[11px] text-slate-500">
            Each stacked segment is one session · hover a segment for details
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 text-[11px] font-medium text-slate-600">
          {(["easy", "quality", "bike", "strength"] as const).map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1.5">
              <span
                className={`h-2.5 w-2.5 rounded-xs ${CATEGORY_META[cat].dotClass}`}
              />
              {CATEGORY_META[cat].label}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5 text-slate-500">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 rounded-xs border border-slate-400"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(135deg, #94A3B8 0 2px, transparent 2px 4px)",
              }}
            />
            Planned
          </span>
        </div>
      </div>

      <div
        className="h-72 w-full"
        onMouseLeave={() => setHovered(null)}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            barGap={3}
            margin={{ top: 8, right: hasXt ? 4 : 12, left: -12, bottom: 0 }}
          >
            <defs>
              {(Object.keys(CATEGORY_META) as AuditSessionCategory[]).map(
                (cat) => {
                  const color = CATEGORY_META[cat].color;
                  return (
                    <pattern
                      key={cat}
                      id={patternId(cat)}
                      width="6"
                      height="6"
                      patternUnits="userSpaceOnUse"
                      patternTransform="rotate(45)"
                    >
                      <rect
                        width="6"
                        height="6"
                        fill={color}
                        fillOpacity={0.35}
                      />
                      <line
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="6"
                        stroke={color}
                        strokeWidth="2.5"
                        strokeOpacity={0.85}
                      />
                    </pattern>
                  );
                },
              )}
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
              unit=" km"
              tick={{ fontSize: 11, fill: "#64748B" }}
              axisLine={false}
              tickLine={false}
            />
            {hasXt && (
              <YAxis
                yAxisId="min"
                orientation="right"
                unit="m"
                tick={{ fontSize: 11, fill: "#8B5CF6" }}
                axisLine={false}
                tickLine={false}
              />
            )}

            <Tooltip
              cursor={{ fill: "rgba(241, 245, 249, 0.7)" }}
              content={(props) => (
                <AuditTooltip
                  active={props.active}
                  payload={props.payload as Array<{ payload?: ChartRow }> | undefined}
                  hovered={hovered}
                />
              )}
            />

            {runIndices.map((idx) => (
              <Bar
                key={`run_${idx}`}
                yAxisId="km"
                dataKey={`run_${idx}`}
                stackId="runs"
                maxBarSize={38}
                radius={idx === maxRuns - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                isAnimationActive={false}
                onMouseLeave={() => setHovered(null)}
              >
                {rows.map((row, wIdx) => {
                  const s = row.runs[idx];
                  return (
                    <Cell
                      key={`run-cell-${wIdx}-${idx}`}
                      fill={fillFor(s)}
                      stroke={strokeFor(s)}
                      strokeWidth={s ? 1.5 : 0}
                      onMouseEnter={() => {
                        if (s) setHovered({ weekIdx: wIdx, session: s });
                      }}
                    />
                  );
                })}
              </Bar>
            ))}

            {xtIndices.map((idx) => (
              <Bar
                key={`xt_${idx}`}
                yAxisId="min"
                dataKey={`xt_${idx}`}
                stackId="xt"
                maxBarSize={14}
                radius={idx === maxXts - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
                isAnimationActive={false}
                onMouseLeave={() => setHovered(null)}
              >
                {rows.map((row, wIdx) => {
                  const s = row.xts[idx];
                  return (
                    <Cell
                      key={`xt-cell-${wIdx}-${idx}`}
                      fill={fillFor(s)}
                      stroke={strokeFor(s)}
                      strokeWidth={s ? 1.5 : 0}
                      onMouseEnter={() => {
                        if (s) setHovered({ weekIdx: wIdx, session: s });
                      }}
                    />
                  );
                })}
              </Bar>
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Long-run targets & calendar notes per week */}
      {annotatedWeeks.length > 0 && (
        <div className="border-t border-slate-100 pt-3 space-y-1.5">
          {annotatedWeeks.map((w, idx) => (
            <div
              key={`${w.week || idx}`}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-slate-600"
            >
              <span className="font-display font-bold text-slate-800">
                {w.date_range || formatChartTickDate(w.week)}:
              </span>
              {w.long_run && (
                <span
                  className={
                    w.long_run.includes("⚠")
                      ? "rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] font-medium text-amber-800"
                      : "text-slate-600"
                  }
                >
                  🏃 {w.long_run}
                </span>
              )}
              {w.notes.map((n, nIdx) => (
                <span
                  key={nIdx}
                  className="rounded-full bg-slate-100 border border-slate-200 px-2 py-0.5 text-[11px] text-slate-700"
                >
                  📝 {n}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditTooltip({
  active,
  payload,
  hovered,
}: {
  active?: boolean;
  payload?: Array<{ payload?: ChartRow }>;
  hovered: HoveredSegment | null;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const w = row.week;
  const activeSession =
    hovered && row.week.sessions.includes(hovered.session)
      ? hovered.session
      : null;

  return (
    <div className="max-w-xs rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-lg space-y-2">
      {activeSession ? (
        <SessionDetail session={activeSession} />
      ) : (
        <WeekSessionList week={w} />
      )}

      <div className="border-t border-slate-100 pt-1.5 text-[11px] text-slate-500">
        <div className="font-semibold text-slate-700">
          {w.date_range || row.label}: {w.km.toFixed(1)} km · TSS{" "}
          {Math.round(w.tss)}
        </div>
        <div>
          {w.easy + w.quality} runs ({w.easy} easy, {w.quality} quality)
          {w.bike > 0 ? ` · ${w.bike} bike` : ""}
          {w.strength > 0 ? ` · ${w.strength} strength` : ""}
        </div>
      </div>
    </div>
  );
}

function SessionDetail({ session }: { session: AuditSession }) {
  const meta = CATEGORY_META[session.category] || CATEGORY_META.other;
  const runSession = isRun(session);
  const volumeParts: string[] = [];
  if (session.km > 0) volumeParts.push(`${session.km.toFixed(1)} km`);
  if (!runSession && session.minutes > 0) {
    volumeParts.push(`${session.minutes} min`);
  } else if (runSession && session.minutes > 0) {
    volumeParts.push(`${session.minutes} min`);
  }
  if (session.tss > 0) volumeParts.push(`TSS ${Math.round(session.tss)}`);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-slate-800">
          <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} />
          {meta.label}
        </span>
        <span
          className={`rounded-full px-1.5 py-0.2 text-[10px] font-semibold ${
            session.completed
              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
              : "bg-slate-100 text-slate-600 border border-slate-200"
          }`}
        >
          {session.completed ? "Completed" : "Planned"}
        </span>
      </div>
      <div className="font-display font-bold text-slate-900">
        {session.title}
      </div>
      <div className="text-[11px] text-slate-600">
        {formatDayShort(session.date)}
        {volumeParts.length > 0 ? ` · ${volumeParts.join(" · ")}` : ""}
      </div>
    </div>
  );
}

function WeekSessionList({ week }: { week: AuditWeek }) {
  if (week.sessions.length === 0) {
    return <div className="text-slate-500">No sessions scheduled</div>;
  }
  return (
    <div className="space-y-1">
      {week.sessions.map((s, idx) => {
        const meta = CATEGORY_META[s.category] || CATEGORY_META.other;
        const measure =
          s.km > 0
            ? `${s.km.toFixed(1)} km`
            : s.minutes > 0
              ? `${s.minutes} min`
              : s.sport;
        return (
          <div key={idx} className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 truncate text-slate-800">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${meta.dotClass}`}
              />
              <span className="font-medium truncate">{s.title}</span>
            </span>
            <span className="shrink-0 tabular-nums text-[11px] text-slate-500">
              {formatDayShort(s.date).split(",")[0]} · {measure}
            </span>
          </div>
        );
      })}
    </div>
  );
}
