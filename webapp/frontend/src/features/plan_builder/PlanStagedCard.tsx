import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bike,
  CalendarPlus,
  Check,
  ChevronLeft,
  ChevronRight,
  Dumbbell,
  Footprints,
  Loader2,
  PersonStanding,
  RefreshCw,
  RotateCw,
  Trophy,
  Waves,
} from "lucide-react";
import type {
  AppliedTrainingPlan,
  PlanRowAction,
  PlanSessionRow,
  PlanWeek,
  StagedTrainingPlan,
} from "../../shared/types";

/** Weeks shown at a time; the arrows page by this many. */
export const PLAN_WINDOW_WEEKS = 4;

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

/** Badge labels/styles consistent with StagedChangesCard (create emerald, update sky, delete rose). */
const BADGE: Record<PlanRowAction, { label: string; className: string }> = {
  create: { label: "New", className: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  update: { label: "Updated", className: "bg-sky-50 text-sky-800 border-sky-200" },
  delete: { label: "Removed", className: "bg-rose-50 text-rose-800 border-rose-200" },
  keep: { label: "Kept", className: "bg-slate-50 text-slate-600 border-slate-200" },
};

const SPORT_ICON: Record<string, typeof Activity> = {
  run: Footprints,
  bike: Bike,
  strength: Dumbbell,
  swim: Waves,
  walk: PersonStanding,
  race: Trophy,
};

function SportIcon({ sport }: { sport: string }) {
  const Icon = SPORT_ICON[sport.toLowerCase()] ?? Activity;
  return <Icon className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-label={sport} role="img" />;
}

/** "12 km" for distance sessions, else "45 min". */
function sessionSize(row: PlanSessionRow): string | null {
  if (row.distance_km) return `${round(row.distance_km)} km`;
  if (row.duration_minutes) return `${Math.round(row.duration_minutes)} min`;
  return null;
}

function SessionChip({ row }: { row: PlanSessionRow }) {
  const badge = BADGE[row.action] ?? BADGE.create;
  const size = sessionSize(row);
  return (
    <li
      data-testid="plan-session"
      title={row.summary || row.code || undefined}
      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/60 px-2 py-1 text-xs"
    >
      <span className="font-semibold text-slate-700">{row.day}</span>
      <span className={`rounded-full border px-1.5 py-px text-[11px] font-semibold ${badge.className}`}>
        {badge.label}
      </span>
      <SportIcon sport={row.sport} />
      <span className={`text-slate-900 ${row.action === "delete" ? "line-through text-slate-500" : ""}`}>
        {row.title}
      </span>
      {size && <span className="tabular-nums text-slate-500">{size}</span>}
    </li>
  );
}

/** "W1 · 30 Nov · Base · 42 km · TSS 290" */
export function weekHeadline(week: PlanWeek): string {
  const parts = [`W${week.week}`, dayMonth(week.start), capitalize(week.phase)];
  if (week.run_km) parts.push(`${round(week.run_km)} km`);
  if (week.bike_minutes) parts.push(`Bike ${Math.round(week.bike_minutes)} min`);
  if (week.tss != null) parts.push(`TSS ${Math.round(week.tss)}`);
  return parts.join(" · ");
}

type WeekState = "done" | "failed" | "applying" | null;

function WeekRow({ week, state }: { week: PlanWeek; state: WeekState }) {
  return (
    <li data-testid="plan-week" className="rounded-xl border border-slate-200 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-display text-sm font-bold text-slate-900 tabular-nums">{weekHeadline(week)}</span>
        {state === "done" && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
            <Check className="h-3.5 w-3.5" /> Applied
          </span>
        )}
        {state === "failed" && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700">
            <AlertTriangle className="h-3.5 w-3.5" /> Failed
          </span>
        )}
        {state === "applying" && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-orange-700">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Applying
          </span>
        )}
        {week.focus && <span className="text-xs text-slate-500">{week.focus}</span>}
      </div>
      {week.rows.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {week.rows.map((row, i) => (
            <SessionChip key={`${row.date}-${row.sport}-${i}`} row={row} />
          ))}
        </ul>
      ) : (
        <p className="text-xs italic text-slate-500">Rest week</p>
      )}
    </li>
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

/** Staged multi-week training plan: 4-week pager, compact week rows, week-by-week apply progress. */
export function PlanStagedCard({ plan, status, applied, applyingWeek, busy, onApply }: PlanStagedCardProps) {
  const weeks = plan.weeks;
  const total = weeks.length;
  const [start, setStart] = useState(0);

  // While applying, the window follows the week being written.
  useEffect(() => {
    if (applyingWeek == null) return;
    const idx = weeks.findIndex((w) => w.week === applyingWeek);
    if (idx >= 0) setStart(Math.floor(idx / PLAN_WINDOW_WEEKS) * PLAN_WINDOW_WEEKS);
  }, [applyingWeek, weeks]);

  const end = Math.min(start + PLAN_WINDOW_WEEKS, total);
  const visible = weeks.slice(start, end);
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
      className="rounded-2xl border border-amber-200/80 bg-white p-5 shadow-card space-y-3"
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

      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Previous 4 weeks"
          disabled={start === 0}
          onClick={() => setStart(Math.max(0, start - PLAN_WINDOW_WEEKS))}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-sm font-semibold text-slate-700 tabular-nums">
          Weeks {total ? start + 1 : 0}–{end} of {total}
        </span>
        <button
          type="button"
          aria-label="Next 4 weeks"
          disabled={end >= total}
          onClick={() => setStart(start + PLAN_WINDOW_WEEKS)}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <ul className="space-y-2">
        {visible.map((w) => (
          <WeekRow key={w.week} week={w} state={weekState(w)} />
        ))}
      </ul>
    </div>
  );
}
