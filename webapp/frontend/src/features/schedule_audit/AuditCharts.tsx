import {
  Activity,
  Bike,
  Check,
  Dumbbell,
  Footprints,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { formatChartTickDate } from "../../shared/format";
import type {
  AuditSession,
  AuditSessionCategory,
  AuditVolumeReference,
  AuditWeek,
  AuditWeekVolume,
} from "../../shared/types";

interface AuditChartsProps {
  weeks: AuditWeek[];
  /** How the weekly km targets are derived; renders the caption under the header. */
  volumeReference?: AuditVolumeReference | null;
  /** ISO date (YYYY-MM-DD) treated as "today"; defaults to the local date. */
  today?: string;
}

function signedPct(value?: number | null): string | null {
  return value == null ? null : `${value > 0 ? "+" : ""}${Math.round(value)}%`;
}

/** Planned km within ±GAP_TOLERANCE_PCT of the target counts as on track. */
const GAP_TOLERANCE_PCT = 10;

type GapTone = "on" | "below" | "above";

/** Neutral palette (amber/violet, not red/green): the target is a reference, the ramp is the coach's call. */
const TONE_CLASSES: Record<GapTone, { text: string; fill: string }> = {
  on: { text: "text-slate-600", fill: "bg-gradient-to-r from-orange-400 to-pink-500" },
  below: { text: "text-amber-600", fill: "bg-amber-400" },
  above: { text: "text-violet-600", fill: "bg-violet-500" },
};

export function gapTone(vsTargetPct?: number | null): GapTone {
  if (vsTargetPct == null || Math.abs(vsTargetPct) <= GAP_TOLERANCE_PCT) return "on";
  return vsTargetPct < 0 ? "below" : "above";
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

/** One-line explanation of where the weekly km targets come from. */
export function volumeCaption(ref: AuditVolumeReference): string {
  const block = ref.goal_label ? `${ref.goal_label} block target` : "block target";
  const ramp =
    ref.start_km != null
      ? `Weekly km targets ramp from your recent level (${Math.round(ref.start_km)} km/wk) to the ${ref.block_target_km} km/wk ${block}`
      : `Weekly km targets build to the ${ref.block_target_km} km/wk ${block}`;
  let basis = "";
  if (ref.ns_goal) {
    basis = ref.own_block
      ? ` (your ${ref.ns_goal} peak)`
      : ref.ns_peak_km
        ? ` (${Math.round((ref.block_target_km / ref.ns_peak_km) * 100)}% of your ${ref.ns_peak_km} km/wk ${ref.ns_goal} peak)`
        : "";
  }
  return (
    `${ramp}${basis}. Every ${ordinal(ref.recovery_every_weeks)} week is a recovery week. ` +
    "Targets are a reference, not a limit."
  );
}

/** Planned week's weekly running-km target (shared north-star rule). Facts only: the ramp is the coach's call. */
function VolumeTarget({ volume, vsPriorPct }: { volume: AuditWeekVolume; vsPriorPct?: number | null }) {
  const tone = gapTone(volume.vs_path_pct);
  const gap = signedPct(volume.vs_path_pct);
  const vsPrior = signedPct(vsPriorPct);
  const phase = volume.phase === "build" ? null : volume.phase;
  const title = [
    `Weekly running-km target${phase ? ` (${phase} week)` : ""}`,
    gap && `planned ${gap} vs target`,
    vsPrior && `${vsPrior} vs prior week`,
    `block target ${volume.block_target_km} km`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs tabular-nums text-slate-500"
      title={title}
      data-testid="volume-target"
      data-tone={tone}
    >
      <span className="h-1.5 w-1.5 rounded-full border border-slate-500" />
      <span>Target {volume.target_km} km</span>
      {gap && <span className={`font-semibold ${TONE_CLASSES[tone].text}`}>{gap}</span>}
      {phase && (
        <span className="rounded bg-slate-100 px-1 text-[0.6875rem] font-semibold text-slate-600">
          {phase}
        </span>
      )}
    </span>
  );
}

/** Weekly km bar: with a target, planned km vs target (tick); otherwise relative to the biggest week. */
function VolumeBar({ km, maxKm, volume }: { km: number; maxKm: number; volume?: AuditWeekVolume | null }) {
  if (!volume) {
    const pct = Math.max(4, Math.round((km / maxKm) * 100));
    return (
      <span className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <span
          className={`block h-full rounded-full ${TONE_CLASSES.on.fill}`}
          style={{ width: `${pct}%` }}
        />
      </span>
    );
  }
  // The larger of planned and target fills 85% of the bar, so an overshoot stays visible.
  const scale = Math.max(km, volume.target_km, 1) / 0.85;
  const fillPct = Math.max(km > 0 ? 4 : 0, Math.round((km / scale) * 100));
  const tickPct = Math.round((volume.target_km / scale) * 100);
  return (
    <span className="relative block h-1.5 w-full rounded-full bg-slate-100">
      <span
        className={`block h-full rounded-full ${TONE_CLASSES[gapTone(volume.vs_path_pct)].fill}`}
        style={{ width: `${fillPct}%` }}
      />
      <span
        data-testid="volume-tick"
        className="absolute -top-0.5 h-2.5 w-0.5 -translate-x-1/2 rounded-full bg-slate-700"
        style={{ left: `${tickPct}%` }}
        aria-hidden="true"
      />
    </span>
  );
}

interface CategoryMeta {
  label: string;
  icon: LucideIcon;
  /** Completed session: solid fill. */
  solid: string;
  /** Planned session: light tint + coloured outline. */
  planned: string;
  swatch: string;
}

const CATEGORY_META: Record<AuditSessionCategory, CategoryMeta> = {
  easy: {
    label: "Easy run",
    icon: Footprints,
    solid: "bg-sky-400 border-sky-400 text-white",
    planned: "bg-sky-50 border-sky-300 text-sky-950",
    swatch: "bg-sky-400",
  },
  quality: {
    label: "Quality run",
    icon: Zap,
    solid: "bg-orange-500 border-orange-500 text-white",
    planned: "bg-orange-50 border-orange-300 text-orange-950",
    swatch: "bg-orange-500",
  },
  bike: {
    label: "Bike",
    icon: Bike,
    solid: "bg-violet-500 border-violet-500 text-white",
    planned: "bg-violet-50 border-violet-300 text-violet-950",
    swatch: "bg-violet-500",
  },
  strength: {
    label: "Strength",
    icon: Dumbbell,
    solid: "bg-emerald-500 border-emerald-500 text-white",
    planned: "bg-emerald-50 border-emerald-300 text-emerald-950",
    swatch: "bg-emerald-500",
  },
  other: {
    label: "Other",
    icon: Activity,
    solid: "bg-slate-400 border-slate-400 text-white",
    planned: "bg-slate-50 border-slate-300 text-slate-900",
    swatch: "bg-slate-400",
  },
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

const GRID_COLS =
  "grid grid-cols-[3.75rem_repeat(7,minmax(5.5rem,1fr))_6rem] gap-1.5";

function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const parts = iso.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const [y, m, d] = parts;
  return new Date(Date.UTC(y, m - 1, d));
}

function toIso(dt: Date): string {
  return dt.toISOString().slice(0, 10);
}

/** 0 = Monday … 6 = Sunday. */
function weekdayIndex(dt: Date): number {
  return (dt.getUTCDay() + 6) % 7;
}

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

export default function AuditCharts({ weeks, volumeReference, today }: AuditChartsProps) {
  if (weeks.length === 0) return null;

  const todayIso = today ?? localTodayIso();
  const maxKm = Math.max(1, ...weeks.map((w) => w.km));
  const hasTargets = weeks.some((w) => w.volume);

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
          {volumeReference && hasTargets && (
            <p className="mt-1 text-xs text-slate-500" data-testid="volume-caption">
              {volumeCaption(volumeReference)}
            </p>
          )}
        </div>

        {/* Legend */}
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
          {hasTargets && (
            <span className="inline-flex items-center gap-1.5 text-slate-500">
              <span className="h-2.5 w-0.5 rounded-full bg-slate-700" />
              Weekly km target
            </span>
          )}
        </div>
      </div>

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

          {weeks.map((w, wIdx) => (
            <WeekRow
              key={w.week ?? wIdx}
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
        <VolumeBar km={week.km} maxKm={maxKm} volume={week.volume} />
        <span className="text-xs tabular-nums text-slate-500">
          TSS {Math.round(week.tss)}
        </span>
        {week.volume ? <VolumeTarget volume={week.volume} vsPriorPct={week.vs_prior_pct} /> : null}
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
