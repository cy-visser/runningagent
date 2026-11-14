import { useState } from "react";
import { Check } from "lucide-react";
import {
  AGENDA_WINDOW_WEEKS,
  AgendaPager,
  CATEGORY_META,
  VolumeBar,
  WEEKDAYS,
  parseIso,
  toIso,
  weekdayIndex,
} from "../../shared/agenda";
import { formatChartTickDate } from "../../shared/format";
import type {
  AuditSession,
  AuditWeek,
} from "../../shared/types";

interface AuditChartsProps {
  weeks: AuditWeek[];
  /** ISO date (YYYY-MM-DD) treated as "today"; defaults to the local date. */
  today?: string;
}

function signedPct(value?: number | null): string | null {
  return value == null ? null : `${value > 0 ? "+" : ""}${Math.round(value)}%`;
}

const GRID_COLS =
  "grid grid-cols-[3.75rem_repeat(7,minmax(5.5rem,1fr))_6rem] gap-1.5";

function localTodayIso(): string {
  const now = new Date();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

function isRun(s: AuditSession): boolean {
  return s.category === "easy" || s.category === "quality";
}

/** Monday of the week, from `week` or (fallback) the first dated session. */
function weekStart(w: AuditWeek): Date | null {
  const fromWeek = parseIso(w.week);
  if (fromWeek) {
    return new Date(fromWeek.getTime() - weekdayIndex(fromWeek) * 86_400_000);
  }
  const first = w.sessions.map((s) => parseIso(s.date)).find(Boolean);
  if (!first) return null;
  return new Date(first.getTime() - weekdayIndex(first) * 86_400_000);
}

function measureFor(s: AuditSession): string {
  if (isRun(s) && s.km > 0) return `${s.km.toFixed(s.km % 1 ? 1 : 0)} km`;
  if (s.minutes > 0) return `${s.minutes} min`;
  if (s.km > 0) return `${s.km.toFixed(1)} km`;
  return s.sport;
}

export default function AuditCharts({ weeks, today }: AuditChartsProps) {
  const [start, setStart] = useState(0);
  if (weeks.length === 0) return null;

  const total = weeks.length;
  const paged = total > AGENDA_WINDOW_WEEKS;
  const pageStart = paged && start < total ? start : 0;
  const end = paged ? Math.min(pageStart + AGENDA_WINDOW_WEEKS, total) : total;
  const visibleWeeks = paged ? weeks.slice(pageStart, end) : weeks;

  const todayIso = today ?? localTodayIso();
  const maxKm = Math.max(1, ...weeks.map((w) => w.km));

  const legend = (
    <div className="flex flex-wrap items-center gap-3 text-xs font-medium text-slate-600">
      {(["easy", "quality", "bike", "strength"] as const).map((cat) => (
        <span key={cat} className="inline-flex items-center gap-1.5">
          <span
            className={`h-2.5 w-2.5 rounded-xs ${CATEGORY_META[cat].swatch}`}
          />
          {CATEGORY_META[cat].label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5 text-slate-500">
        <span className="h-2.5 w-2.5 rounded-xs bg-slate-500" />
        Completed
      </span>
      <span className="inline-flex items-center gap-1.5 text-slate-500">
        <span className="h-2.5 w-2.5 rounded-xs border border-slate-400 bg-slate-50" />
        Planned
      </span>
    </div>
  );

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-xl">
          <h4 className="font-display text-base font-bold text-slate-900">
            Weekly Schedule
          </h4>
          <p className="text-xs text-slate-500">
            Every scheduled session for the audit period
          </p>
        </div>

        {!paged && legend}
      </div>

      {paged && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <AgendaPager
            start={pageStart}
            end={end}
            total={total}
            onPrev={() => setStart(Math.max(0, pageStart - AGENDA_WINDOW_WEEKS))}
            onNext={() => setStart(pageStart + AGENDA_WINDOW_WEEKS)}
          />
          {legend}
        </div>
      )}

      <div className="overflow-x-auto -mx-1 px-1">
        <div className="min-w-[48.75rem] space-y-1.5" role="table" aria-label="Weekly schedule">
          {/* Header */}
          <div className={GRID_COLS} role="row">
            <div
              role="columnheader"
              className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-400"
            >
              Week
            </div>
            {WEEKDAYS.map((d) => (
              <div
                key={d}
                role="columnheader"
                className="text-center text-xs font-semibold uppercase tracking-wide text-slate-400"
              >
                {d}
              </div>
            ))}
            <div
              role="columnheader"
              className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-400"
            >
              Total
            </div>
          </div>

          {visibleWeeks.map((w, wIdx) => (
            <WeekRow
              key={w.week ?? pageStart + wIdx}
              week={w}
              todayIso={todayIso}
              maxKm={maxKm}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function WeekRow({
  week,
  todayIso,
  maxKm,
}: {
  week: AuditWeek;
  todayIso: string;
  maxKm: number;
}) {
  const start = weekStart(week);
  const byDay: AuditSession[][] = WEEKDAYS.map(() => []);
  for (const s of week.sessions) {
    const dt = parseIso(s.date);
    if (dt) byDay[weekdayIndex(dt)].push(s);
  }

  // Long run = the longest easy run of the week.
  const longRun = week.sessions
    .filter((s) => s.category === "easy" && s.km > 0)
    .reduce<AuditSession | null>(
      (best, s) => (!best || s.km > best.km ? s : best),
      null,
    );

  const vsPrior = signedPct(week.vs_prior_pct);

  return (
    <div className={GRID_COLS} role="row">
      <div
        role="rowheader"
        className="flex items-center px-1 font-display text-sm font-bold text-slate-800"
      >
        {formatChartTickDate(week.week) || week.date_range || ""}
      </div>

      {WEEKDAYS.map((_, dIdx) => {
        const dayIso = start
          ? toIso(new Date(start.getTime() + dIdx * 86_400_000))
          : null;
        const isToday = dayIso === todayIso;
        const sessions = byDay[dIdx];
        return (
            <div
              key={dIdx}
              role="cell"
              data-today={isToday || undefined}
              className={`flex min-h-16 flex-col gap-1 rounded-xl p-1 ${
                isToday
                  ? "ring-2 ring-orange-400 bg-orange-50/60"
                  : "bg-slate-50/70"
              }`}
            >
              {isToday && (
                <span className="px-1 text-xs font-semibold uppercase tracking-wide text-orange-600">
                  Today
                </span>
              )}
              {sessions.length === 0 ? (
                <span className="m-auto text-xs font-medium text-slate-300">
                  Rest
                </span>
              ) : (
                sessions.map((s, sIdx) => (
                  <SessionCard
                    key={sIdx}
                    session={s}
                    isLongRun={s === longRun}
                  />
                ))
              )}
            </div>
        );
      })}

      <div
        role="cell"
        className="flex flex-col justify-center gap-1 px-1"
      >
        <span className="font-display text-base font-bold tabular-nums text-slate-900">
          {week.km.toFixed(1)} km
        </span>
        <VolumeBar km={week.km} maxKm={maxKm} />
        <span className="text-xs tabular-nums text-slate-500">
          TSS {Math.round(week.tss)}
        </span>
        {vsPrior ? (
          <span
            className="text-xs tabular-nums text-slate-500"
            data-testid="vs-prior"
          >
            {vsPrior} vs prior
          </span>
        ) : null}
      </div>
    </div>
  );
}

function SessionCard({
  session,
  isLongRun,
}: {
  session: AuditSession;
  isLongRun: boolean;
}) {
  const meta = CATEGORY_META[session.category] || CATEGORY_META.other;
  const Icon = meta.icon;
  const status = session.completed ? "Completed" : "Planned";
  const tooltip = `${session.title} · ${measureFor(session)}${
    session.tss > 0 ? ` · TSS ${Math.round(session.tss)}` : ""
  } · ${status}`;

  return (
    <div
      title={tooltip}
      aria-label={tooltip}
      className={`rounded-lg border px-1.5 py-1 shadow-2xs ${
        session.completed ? meta.solid : meta.planned
      }`}
    >
      <div className="flex items-start gap-1">
        <Icon className="mt-[1px] h-3 w-3 shrink-0 opacity-80" />
        <span className="line-clamp-3 text-xs font-semibold leading-tight">
          {session.title}
        </span>
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-1 text-xs tabular-nums">
        <span className="inline-flex items-center gap-0.5 opacity-90">
          {measureFor(session)}
          {session.completed && <Check className="h-2.5 w-2.5" />}
        </span>
        {isLongRun && (
          <span
            className={`rounded px-1 text-[0.6875rem] font-bold ${
              session.completed
                ? "bg-white/25 text-white"
                : "bg-white text-sky-700 border border-sky-200"
            }`}
          >
            LR
          </span>
        )}
      </div>
    </div>
  );
}
