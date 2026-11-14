import {
  Activity,
  Bike,
  ChevronLeft,
  ChevronRight,
  Dumbbell,
  Footprints,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { AuditSessionCategory } from "./types";

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** Weeks shown at a time in paged mode; the arrows page by this many. */
export const AGENDA_WINDOW_WEEKS = 4;

export function AgendaPager({
  start,
  end,
  total,
  onPrev,
  onNext,
}: {
  start: number;
  end: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="agenda-pager">
      <button
        type="button"
        aria-label={`Previous ${AGENDA_WINDOW_WEEKS} weeks`}
        disabled={start === 0}
        onClick={onPrev}
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="text-sm font-semibold text-slate-700 tabular-nums">
        Weeks {total ? start + 1 : 0}–{end} of {total}
      </span>
      <button
        type="button"
        aria-label={`Next ${AGENDA_WINDOW_WEEKS} weeks`}
        disabled={end >= total}
        onClick={onNext}
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}

/** Weekly km bar relative to the biggest week in the window. */
export function VolumeBar({
  km,
  maxKm,
}: {
  km: number;
  maxKm: number;
}) {
  const pct = km > 0 ? Math.max(4, Math.round((km / Math.max(1, maxKm)) * 100)) : 0;
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <span
        className="block h-full rounded-full bg-gradient-to-r from-orange-400 to-pink-500"
        style={{ width: `${pct}%` }}
      />
    </span>
  );
}

export interface CategoryMeta {
  label: string;
  icon: LucideIcon;
  /** Completed session: solid fill. */
  solid: string;
  /** Planned session: light tint + coloured outline. */
  planned: string;
  swatch: string;
}

export const CATEGORY_META: Record<AuditSessionCategory, CategoryMeta> = {
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

export function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const parts = iso.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const [y, m, d] = parts;
  return new Date(Date.UTC(y, m - 1, d));
}

export function toIso(dt: Date): string {
  return dt.toISOString().slice(0, 10);
}

/** 0 = Monday … 6 = Sunday. */
export function weekdayIndex(dt: Date): number {
  return (dt.getUTCDay() + 6) % 7;
}
