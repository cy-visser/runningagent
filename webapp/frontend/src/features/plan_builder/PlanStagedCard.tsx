import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bike,
  CalendarPlus,
  Check,
  Dumbbell,
  Footprints,
  Loader2,
  PersonStanding,
  RefreshCw,
  RotateCw,
  Trophy,
  Waves,
  Zap,
} from "lucide-react";
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
import type {
  AppliedTrainingPlan,
  AuditSessionCategory,
  PlanRowAction,
  PlanSessionRow,
  PlanWeek,
  StagedTrainingPlan,
} from "../../shared/types";

/** Weeks shown at a time in paged mode; the arrows page by this many. */
export const PLAN_WINDOW_WEEKS = AGENDA_WINDOW_WEEKS;

export type PlanStatus = "pending" | "applying" | "applied" | "partial" | "replaced";

interface PlanStagedCardProps {
  plan: StagedTrainingPlan;
  status: PlanStatus;
  /** Latest `applied_training_plan` for this plan (progress, failed weeks). */
  applied?: AppliedTrainingPlan | null;
  /** Week currently being written (status "applying"); the window follows it. */
  applyingWeek?: number | null;
  /** Another request is streaming: the button waits. */
  busy?: boolean;
  /** Apply (or resume) the remaining weeks. */
  onApply: (stagedId: string) => void;
}

const AGENDA_GRID_COLS =
  "grid grid-cols-[4.75rem_repeat(7,minmax(5.5rem,1fr))_6.25rem] gap-1.5";

const QUALITY_TITLE_RE =
  /(interval|tempo|threshold|speed|reps|\bmp\b|marathon pace|race pace|canova|progression|hills?\b|fartlek|vo2|\bpush\b|\d+\s*x\s*\d+)/i;
const QUALITY_CODE_RE = /^(T|I|Rp|RP|M|P|H|RACE)\b/;

function dayMonth(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function round(value: number, digits = 1): number {
  return Number(value.toFixed(digits));
}

/** Effective display start date of a week (clamped to `planStartDate` so W1 never shows a pre-plan date). */
export function effectiveWeekStart(week: PlanWeek, planStartDate?: string | null): string {
  if (planStartDate && week.start < planStartDate) {
    return planStartDate;
  }
  return week.start;
}

/** Category of a staged row (uses backend `row.category`, falling back for older persisted plans). */
export function inferPlanCategory(row: PlanSessionRow): AuditSessionCategory {
  if (row.category) return row.category;
  const sport = row.sport.toLowerCase();
  if (sport === "bike" || sport === "cycling") return "bike";
  if (sport === "strength" || sport === "gym") return "strength";
  if (sport === "race") return "quality";
  if (sport === "run" || sport === "running") {
    const code = (row.code ?? "").trim();
    if (QUALITY_CODE_RE.test(code) || code.includes("@") || QUALITY_TITLE_RE.test(row.title)) {
      return "quality";
    }
    return "easy";
  }
  return "other";
}

/** Badge labels/styles consistent with StagedChangesCard (create emerald, update sky, delete rose). */
const BADGE: Record<PlanRowAction, { label: string; className: string }> = {
  create: { label: "New", className: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  update: { label: "Updated", className: "bg-sky-50 text-sky-800 border-sky-200" },
  delete: { label: "Removed", className: "bg-rose-100 text-rose-800 border-rose-200" },
  keep: { label: "Kept", className: "bg-white/90 text-slate-600 border-slate-200" },
};

const SPORT_ICON: Record<string, typeof Activity> = {
  run: Footprints,
  bike: Bike,
  strength: Dumbbell,
  swim: Waves,
  walk: PersonStanding,
  race: Trophy,
};

function SportIcon({ sport, category }: { sport: string; category: AuditSessionCategory }) {
  const low = sport.toLowerCase();
  const Icon =
    low === "run" && category === "quality"
      ? Zap
      : SPORT_ICON[low] ?? CATEGORY_META[category]?.icon ?? Activity;
  return <Icon className="mt-[1px] h-3 w-3 shrink-0 opacity-80" aria-label={sport} role="img" />;
}

/** "12 km" for distance sessions, else "45 min". */
function sessionSize(row: PlanSessionRow): string | null {
  if (row.distance_km) return `${round(row.distance_km)} km`;
  if (row.duration_minutes) return `${Math.round(row.duration_minutes)} min`;
  return null;
}

function PlanSessionCard({
  row,
  isLongRun,
}: {
  row: PlanSessionRow;
  isLongRun: boolean;
}) {
  const cat = inferPlanCategory(row);
  const meta = CATEGORY_META[cat] ?? CATEGORY_META.other;
  const badge = BADGE[row.action] ?? BADGE.create;
  const size = sessionSize(row);
  const isDeleted = row.action === "delete";
  const tooltip = [
    row.day,
    row.time,
    row.title,
    size,
    row.tss_planned != null ? `TSS ${Math.round(row.tss_planned)}` : null,
    row.summary || row.code,
    badge.label,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      data-testid="plan-session"
      data-category={cat}
      title={tooltip || undefined}
      className={`rounded-lg border px-1.5 py-1 shadow-2xs ${
        isDeleted ? "bg-rose-50/70 border-rose-200 text-rose-900" : meta.planned
      }`}
    >
      <div className="flex items-start gap-1">
        <SportIcon sport={row.sport} category={cat} />
        <span
          className={`line-clamp-3 text-xs font-semibold leading-tight ${
            isDeleted ? "line-through text-slate-500" : ""
          }`}
        >
          {row.title}
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center justify-between gap-1 text-[11px] tabular-nums">
        <span className="inline-flex flex-wrap items-center gap-1 opacity-90">
          {row.time && <span className="text-slate-500">{row.time}</span>}
          {size && <span>{size}</span>}
        </span>

        <span className="inline-flex items-center gap-1">
          {isLongRun && (
            <span className="rounded bg-white px-1 text-[0.65rem] font-bold text-sky-700 border border-sky-200">
              LR
            </span>
          )}
          <span
            className={`rounded-full border px-1.5 py-px text-[10px] font-semibold leading-tight ${badge.className}`}
          >
            {badge.label}
          </span>
        </span>
      </div>
    </div>
  );
}

/** Planned (not removed) strength sessions of a week that carry an exercise list. */
export function strengthRows(week: PlanWeek): PlanSessionRow[] {
  return week.rows.filter(
    (row) => row.sport === "Strength" && row.action !== "delete" && (row.exercises?.length ?? 0) > 0,
  );
}

/** Collapsible "Strength exercises (n)": per session the day, title, duration, exercises and load. */
function StrengthExercises({ rows }: { rows: PlanSessionRow[] }) {
  if (rows.length === 0) return null;
  return (
    <details data-testid="strength-exercises" className="group rounded-lg border border-slate-200 bg-white text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 font-semibold text-slate-700 select-none">
        <Dumbbell className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
        Strength exercises ({rows.length})
      </summary>
      <ul className="space-y-2 border-t border-slate-100 px-2.5 py-2">
        {rows.map((row, i) => {
          const size = sessionSize(row);
          return (
            <li key={`${row.date}-${i}`} data-testid="strength-session">
              <p className="font-semibold text-slate-800">
                {[row.day, row.time, row.title, size].filter(Boolean).join(" · ")}
              </p>
              <ul className="mt-0.5 list-disc pl-4 text-slate-700">
                {row.exercises?.map((exercise) => <li key={exercise}>{exercise}</li>)}
              </ul>
              {row.load && <p className="mt-0.5 text-slate-500">{row.load}</p>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

/** "W1 · 30 Nov · Base · 42 km · TSS 290" (clamped to `planStartDate` when W1 starts mid-week). */
export function weekHeadline(week: PlanWeek, planStartDate?: string | null): string {
  const startIso = effectiveWeekStart(week, planStartDate);
  const parts = [`W${week.week}`, dayMonth(startIso), capitalize(week.phase)];
  if (week.run_km) parts.push(`${round(week.run_km)} km`);
  if (week.bike_minutes) parts.push(`Bike ${Math.round(week.bike_minutes)} min`);
  if (week.tss != null) parts.push(`TSS ${Math.round(week.tss)}`);
  return parts.join(" · ");
}

function weekMonday(week: PlanWeek): Date | null {
  const dt = parseIso(week.start);
  if (!dt) return null;
  return new Date(dt.getTime() - weekdayIndex(dt) * 86_400_000);
}

function dayIndexForRow(row: PlanSessionRow): number {
  const byLabel = WEEKDAYS.indexOf(row.day as (typeof WEEKDAYS)[number]);
  if (byLabel >= 0) return byLabel;
  const dt = parseIso(row.date);
  return dt ? weekdayIndex(dt) : 0;
}

type WeekState = "done" | "failed" | "applying" | null;

function AgendaWeekRow({
  week,
  state,
  maxKm,
  planStartDate,
  planEndDate,
}: {
  week: PlanWeek;
  state: WeekState;
  maxKm: number;
  planStartDate?: string | null;
  planEndDate?: string | null;
}) {
  const monday = weekMonday(week);
  const byDay: PlanSessionRow[][] = WEEKDAYS.map(() => []);
  for (const r of week.rows) {
    byDay[dayIndexForRow(r)].push(r);
  }

  const runCandidates = week.rows.filter(
    (r) => r.sport.toLowerCase() === "run" && r.action !== "delete" && (r.distance_km ?? 0) > 0,
  );
  const explicitLong = runCandidates.filter(
    (r) => /^L\b/i.test((r.code ?? "").trim()) || /^long\b/i.test(r.title),
  );
  const longPool =
    explicitLong.length > 0 ? explicitLong : runCandidates.filter((r) => inferPlanCategory(r) === "easy");
  const longRun = longPool.reduce<PlanSessionRow | null>(
    (best, r) => (!best || (r.distance_km ?? 0) > (best.distance_km ?? 0) ? r : best),
    null,
  );

  const displayStart = effectiveWeekStart(week, planStartDate);
  const sRows = strengthRows(week);
  const km = week.run_km ?? 0;

  return (
    <div data-testid="plan-week" className="space-y-1.5">
      <div className={AGENDA_GRID_COLS} role="row" aria-label={weekHeadline(week, planStartDate)}>
        {/* Week header column */}
        <div
          role="rowheader"
          title={week.focus || undefined}
          className="flex flex-col justify-center gap-0.5 px-1"
        >
          <span className="font-display text-sm font-bold text-slate-900 tabular-nums">
            W{week.week}
          </span>
          <span className="text-xs font-medium text-slate-600 tabular-nums">
            {" "}· {dayMonth(displayStart)}
          </span>
          {week.phase && (
            <span className="w-fit rounded bg-slate-100 px-1.5 py-px text-[0.6875rem] font-semibold text-slate-700">
              {capitalize(week.phase)}
            </span>
          )}
          {week.focus && (
            <span className="line-clamp-2 text-[11px] leading-tight text-slate-500">
              {week.focus}
            </span>
          )}
          {state === "done" && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-emerald-700">
              <Check className="h-3 w-3" /> Applied
            </span>
          )}
          {state === "failed" && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-rose-700">
              <AlertTriangle className="h-3 w-3" /> Failed
            </span>
          )}
          {state === "applying" && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-orange-700">
              <Loader2 className="h-3 w-3 animate-spin" /> Applying
            </span>
          )}
        </div>

        {/* Mon – Sun day cells */}
        {WEEKDAYS.map((_, dIdx) => {
          const dayIso = monday ? toIso(new Date(monday.getTime() + dIdx * 86_400_000)) : null;
          const outOfWindow =
            dayIso != null &&
            ((Boolean(planStartDate) && dayIso < planStartDate!) ||
              (Boolean(planEndDate) && dayIso > planEndDate!));
          const sessions = byDay[dIdx];
          return (
            <div
              key={dIdx}
              role="cell"
              data-out-of-window={outOfWindow || undefined}
              className={`flex min-h-16 flex-col gap-1 rounded-xl p-1 ${
                outOfWindow && sessions.length === 0 ? "bg-slate-100/60" : "bg-slate-50/70"
              }`}
            >
              {sessions.length === 0 ? (
                <span className="m-auto text-xs font-medium text-slate-300">
                  {outOfWindow ? "–" : "Rest"}
                </span>
              ) : (
                sessions.map((row, sIdx) => (
                  <PlanSessionCard
                    key={`${row.date}-${row.sport}-${sIdx}`}
                    row={row}
                    isLongRun={row === longRun}
                  />
                ))
              )}
            </div>
          );
        })}

        {/* Weekly totals column */}
        <div role="cell" className="flex flex-col justify-center gap-1 px-1">
          <span className="font-display text-base font-bold tabular-nums text-slate-900">
            {km.toFixed(1)} km
          </span>
          <VolumeBar km={km} maxKm={maxKm} />
          {week.tss != null && (
            <span className="text-xs tabular-nums text-slate-500">
              TSS {Math.round(week.tss)}
            </span>
          )}
          {Boolean(week.bike_minutes) && (
            <span className="text-xs tabular-nums text-slate-500">
              Bike {Math.round(week.bike_minutes!)} min
            </span>
          )}
        </div>
      </div>

      <StrengthExercises rows={sRows} />
    </div>
  );
}

function ApplyButton({
  status,
  busy,
  onClick,
}: {
  status: PlanStatus;
  busy?: boolean;
  onClick: () => void;
}) {
  if (status === "applied") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2 text-sm font-semibold text-emerald-800">
        <Check className="h-4 w-4" /> Applied to TrainingPeaks
      </span>
    );
  }
  if (status === "replaced") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-xl bg-slate-50 border border-slate-200 px-4 py-2 text-sm font-medium text-slate-500">
        <RefreshCw className="h-4 w-4" /> Replaced by a newer plan
      </span>
    );
  }
  const applying = status === "applying";
  const resume = status === "partial";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={applying || busy}
      className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-4 py-2 text-sm font-semibold text-white shadow-sunset cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
    >
      {applying ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : resume ? (
        <RotateCw className="h-4 w-4" />
      ) : (
        <CalendarPlus className="h-4 w-4" />
      )}
      {applying ? "Applying…" : resume ? "Resume" : "Apply to TrainingPeaks"}
    </button>
  );
}

/** Staged multi-week training plan rendered in Plan Audit's 7-day Mon–Sun agenda grid. */
export function PlanStagedCard({ plan, status, applied, applyingWeek, busy, onApply }: PlanStagedCardProps) {
  const weeks = plan.weeks;
  const total = weeks.length;
  const [start, setStart] = useState(0);

  // While applying, the 4-week window follows the week being written.
  useEffect(() => {
    if (applyingWeek == null) return;
    const idx = weeks.findIndex((w) => w.week === applyingWeek);
    if (idx >= 0) setStart(Math.floor(idx / PLAN_WINDOW_WEEKS) * PLAN_WINDOW_WEEKS);
  }, [applyingWeek, weeks]);

  const end = Math.min(start + PLAN_WINDOW_WEEKS, total);
  const visible = weeks.slice(start, end);
  const maxKm = Math.max(1, ...weeks.map((w) => w.run_km ?? 0));
  const done = new Set(applied?.weeks_done ?? []);
  const failed = new Set(applied?.failed_weeks ?? []);
  const weekState = (w: PlanWeek): WeekState => {
    if (status === "applying" && w.week === applyingWeek) return "applying";
    if (done.has(w.week)) return "done";
    if (failed.has(w.week)) return "failed";
    return null;
  };

  const t = plan.totals;
  const sessions = t?.sessions ?? weeks.reduce((n, w) => n + w.rows.length, 0);
  const countParts = [
    t?.create ? `${t.create} new` : null,
    t?.update ? `${t.update} updated` : null,
    t?.delete ? `${t.delete} removed` : null,
    t?.keep ? `${t.keep} kept` : null,
  ].filter(Boolean);

  const doneCount = weeks.filter((w) => done.has(w.week)).length;
  const pct = total ? Math.round((doneCount / total) * 100) : 0;
  const applyingIndex = applyingWeek != null ? weeks.findIndex((w) => w.week === applyingWeek) + 1 : 0;

  return (
    <div
      data-testid="plan-staged"
      className="rounded-2xl border border-amber-200/80 bg-white p-5 shadow-card space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-bold text-slate-900">Proposed training plan</h3>
          <p className="text-sm text-slate-600">
            {plan.title} · {sessions} sessions
            {countParts.length > 0 && ` (${countParts.join(" · ")})`}
          </p>
        </div>
        <ApplyButton status={status} busy={busy} onClick={() => onApply(plan.staged_id)} />
      </div>

      {status === "applying" && (
        <div className="space-y-1" role="status">
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-sunset transition-all"
              style={{ width: `${pct}%` }}
              data-testid="plan-progress"
            />
          </div>
          <p className="text-xs font-medium text-slate-600">
            Applying week {applyingIndex || doneCount + 1} of {total}…
          </p>
        </div>
      )}

      {status === "partial" && (
        <p className="flex items-center gap-1.5 text-sm text-rose-800" role="status">
          <AlertTriangle className="h-4 w-4 text-rose-600" />
          {doneCount} of {total} weeks applied
          {failed.size > 0 && ` · failed: ${[...failed].sort((a, b) => a - b).map((w) => `W${w}`).join(", ")}`}
          . Press Resume to apply the rest.
        </p>
      )}

      {/* Pager & category legend */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <AgendaPager
          start={start}
          end={end}
          total={total}
          onPrev={() => setStart(Math.max(0, start - PLAN_WINDOW_WEEKS))}
          onNext={() => setStart(start + PLAN_WINDOW_WEEKS)}
        />

        <div className="flex flex-wrap items-center gap-3 text-xs font-medium text-slate-600">
          {(["easy", "quality", "bike", "strength"] as const).map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1.5">
              <span className={`h-2.5 w-2.5 rounded-xs ${CATEGORY_META[cat].swatch}`} />
              {CATEGORY_META[cat].label}
            </span>
          ))}
        </div>
      </div>

      {/* 7-column Mon–Sun Agenda Grid */}
      <div className="overflow-x-auto -mx-1 px-1">
        <div
          className="min-w-[49.5rem] space-y-2"
          role="table"
          aria-label="Proposed weekly schedule"
        >
          <div className={AGENDA_GRID_COLS} role="row">
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

          {visible.map((w) => (
            <AgendaWeekRow
              key={w.week}
              week={w}
              state={weekState(w)}
              maxKm={maxKm}
              planStartDate={plan.start_date}
              planEndDate={plan.end_date}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
