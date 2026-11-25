import { Suspense, lazy, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  Award,
  CheckCircle2,
  ChevronDown,
  Clock,
  Footprints,
  Link2,
  Loader2,
  MessageSquare,
  RefreshCw,
  TrendingUp,
  Trophy,
  X,
} from "lucide-react";
import { fetchYearReview, refreshYearReview } from "../../shared/api";
import { formatDuration, formatShortDate } from "../../shared/format";
import { StatusBadge, directionFromArrow } from "../../shared/RichMarkdown";
import type {
  YearReviewData,
  YearReviewRace,
  YearReviewRefreshMode,
  YearReviewResponse,
  YearReviewSummaryItem,
} from "../../shared/types";
import { ActivityHeatmap } from "./ActivityHeatmap";

const YearReviewChart = lazy(() => import("./YearReviewChart"));

interface YearReviewModalProps {
  open: boolean;
  canDiscuss?: boolean;
  onClose: () => void;
  onOpenTrainingPeaks: () => void;
  onDiscussWithCoach?: (prompt: string) => void;
}

const SPORT_COLORS: Record<string, { bar: string; dot: string }> = {
  running: { bar: "bg-sunset", dot: "bg-orange-500" },
  cycling: { bar: "bg-sky-500", dot: "bg-sky-500" },
  strength: { bar: "bg-violet-500", dot: "bg-violet-500" },
  other: { bar: "bg-slate-400", dot: "bg-slate-400" },
};

function formatHoursMinutes(hours: number): string {
  const totalMin = Math.round(Math.max(0, hours) * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function formatGoalGap(
  gapS: number,
  goalText?: string | null,
): { label: string; tone: "emerald" | "amber" | "rose" } {
  const abs = formatDuration(Math.abs(gapS));
  const suffix = goalText ? ` vs ${goalText}` : " vs goal";
  if (gapS <= 0) {
    return {
      label: gapS === 0 ? `On target${suffix}` : `${abs} ahead${suffix}`,
      tone: "emerald",
    };
  }
  return {
    label: `+${abs} behind${suffix}`,
    tone: gapS <= 60 ? "amber" : "rose",
  };
}

/** Builds a compact, grounded prompt so the coach can reflect on the selected calendar year. */
export function buildDiscussYearPrompt(data: YearReviewData): string {
  const { kpis, races, fitness_shift } = data;
  const scopeLabel = data.is_complete
    ? `calendar year ${data.year}`
    : `calendar year ${data.year} YTD`;
  const parts: string[] = [
    `Reflect on my ${scopeLabel} annual review (${formatShortDate(data.window.start)} – ${formatShortDate(data.window.end)}) and help me shape priorities going forward.`,
    `Totals: ${kpis.total_run_km.toLocaleString("en-US", { maximumFractionDigits: 0 })} km across ${kpis.total_runs} runs (${kpis.avg_weekly_run_km} km/wk avg, ${formatHoursMinutes(kpis.total_hours)} total training, ${kpis.active_weeks}/${kpis.total_weeks} active weeks, longest streak ${kpis.longest_streak_weeks}w).`,
  ];
  if (kpis.ctl_start != null && kpis.ctl_end != null) {
    parts.push(
      `Fitness (CTL): ${kpis.ctl_start} → ${kpis.ctl_end}${kpis.ctl_peak != null ? ` (peak ${kpis.ctl_peak})` : ""}.`,
    );
  }
  if (races.length > 0) {
    const raceSummary = races
      .slice(0, 5)
      .map(
        (r) =>
          `${r.name} (${r.date}${r.duration_s ? `, ${formatDuration(r.duration_s)}` : ""}${r.is_pr ? ", PR" : ""})`,
      )
      .join("; ");
    parts.push(`Main races: ${raceSummary}.`);
  }
  if (fitness_shift.length > 0) {
    const shiftSummary = fitness_shift
      .map((s) => `${s.label} ${s.start} → ${s.latest} (${s.delta})`)
      .join("; ");
    parts.push(`Shifts: ${shiftSummary}.`);
  }
  parts.push(
    "What were my biggest breakthroughs, where are the remaining limiters, and what should I focus on next?",
  );
  return parts.join(" ");
}

function RaceBadgePill({ badge }: { badge: string }) {
  if (badge === "A Race") {
    return (
      <span className="inline-flex items-center rounded-full bg-sunset px-2.5 py-0.5 text-[0.6875rem] font-semibold text-white">
        A Race
      </span>
    );
  }
  if (badge === "Sub-Goal") {
    return (
      <span className="inline-flex items-center rounded-full border border-violet-300 bg-violet-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-violet-800">
        Sub-Goal
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-slate-600">
      {badge}
    </span>
  );
}

function RaceCard({ race }: { race: YearReviewRace }) {
  const featured = race.is_pr || race.badge === "A Race" || race.badge === "Sub-Goal";
  const goalDelta =
    race.goal_gap_s != null ? formatGoalGap(race.goal_gap_s, race.goal_text) : null;

  return (
    <div
      className={`rounded-2xl border p-4 space-y-2.5 ${
        featured
          ? "border-orange-200/90 bg-gradient-to-b from-orange-50/45 to-white"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            <RaceBadgePill badge={race.badge} />
            {race.is_pr && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[0.6875rem] font-semibold text-amber-800">
                ★ New PR
              </span>
            )}
          </div>
          <h4 className="font-display text-sm font-bold text-slate-900 truncate" title={race.name}>
            {race.name}
          </h4>
          <p className="text-xs text-slate-500 mt-0.5 tabular-nums">
            {formatShortDate(race.date)}
            {race.distance_km != null ? ` · ${race.distance_km.toFixed(1)} km` : ""}
          </p>
        </div>

        {race.duration_s != null && (
          <div className="text-right shrink-0 tabular-nums">
            <p className="font-display text-xl font-bold text-slate-900 leading-tight">
              {formatDuration(race.duration_s)}
            </p>
            {race.pace_s != null && (
              <p className="text-xs font-semibold text-orange-600 mt-0.5">
                {formatDuration(Math.round(race.pace_s))} /km
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2 text-[0.6875rem] text-slate-600 tabular-nums">
        <span>
          {race.avg_hr != null ? (
            <>
              Avg HR <strong className="text-slate-800">{race.avg_hr} bpm</strong>
              {race.pct_lthr != null ? ` (${race.pct_lthr}% LTHR)` : ""}
            </>
          ) : null}
          {race.avg_hr != null && race.ctl != null ? " · " : null}
          {race.ctl != null ? `CTL ${race.ctl.toFixed(0)}` : null}
          {race.avg_hr == null && race.ctl == null ? "Completed race" : null}
        </span>

        {goalDelta ? (
          <StatusBadge tone={goalDelta.tone} label={goalDelta.label} size="sm" />
        ) : race.pa_hr != null ? (
          <StatusBadge
            tone={race.pa_hr <= 5 ? "emerald" : "amber"}
            label={`Pa:Hr ${race.pa_hr.toFixed(1)}%`}
            size="sm"
          />
        ) : race.note ? (
          <span className="truncate max-w-[14rem] text-slate-500">{race.note}</span>
        ) : null}
      </div>
    </div>
  );
}

export function YearReviewModal({
  open,
  canDiscuss = true,
  onClose,
  onOpenTrainingPeaks,
  onDiscussWithCoach,
}: YearReviewModalProps) {
  const [selectedYear, setSelectedYear] = useState<number | undefined>(undefined);
  const [res, setRes] = useState<YearReviewResponse | null>(null);
  const [availableYears, setAvailableYears] = useState<YearReviewSummaryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMenuOpen, setRefreshMenuOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const yearCacheRef = useRef<Record<number, YearReviewResponse>>({});
  const refreshMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      setSelectedYear(undefined);
      setRefreshMenuOpen(false);
      yearCacheRef.current = {};
      return;
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (refreshMenuOpen) {
          setRefreshMenuOpen(false);
        } else {
          onClose();
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose, refreshMenuOpen]);

  useEffect(() => {
    if (!refreshMenuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (refreshMenuRef.current && !refreshMenuRef.current.contains(e.target as Node)) {
        setRefreshMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [refreshMenuOpen]);

  useEffect(() => {
    if (!open) return;
    if (selectedYear != null && yearCacheRef.current[selectedYear]) {
      setRes(yearCacheRef.current[selectedYear]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchYearReview(selectedYear)
      .then((data) => {
        if (cancelled) return;
        setRes(data);
        const resolvedYear = data.data?.year ?? data.year;
        if (data.available_years && data.available_years.length > 0) {
          setAvailableYears(data.available_years);
        } else if (resolvedYear != null) {
          setAvailableYears([
            {
              year: resolvedYear,
              total_run_km: data.data?.kpis.total_run_km ?? null,
              total_workouts: data.data?.kpis.total_workouts ?? null,
              races_count: data.data?.races.length ?? null,
              is_complete: Boolean(data.data?.is_complete),
              as_of_date: data.data?.as_of_date ?? null,
            },
          ]);
        }
        if (resolvedYear != null && (data.status === "ready" || data.status === "empty")) {
          yearCacheRef.current[resolvedYear] = data;
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not load your annual review.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, selectedYear]);

  if (!open) return null;

  const activeYear = res?.data?.year ?? selectedYear ?? res?.year ?? new Date().getFullYear();

  const handleRefresh = async (mode: YearReviewRefreshMode = "incremental") => {
    if (refreshing || loading) return;
    setRefreshMenuOpen(false);
    setRefreshing(true);
    setError(null);
    try {
      const updated = await refreshYearReview(activeYear, mode);
      setRes(updated);
      if (updated.available_years && updated.available_years.length > 0) {
        setAvailableYears(updated.available_years);
      }
      const yr = updated.data?.year ?? updated.year ?? activeYear;
      if (updated.status === "ready" || updated.status === "empty") {
        yearCacheRef.current[yr] = updated;
      } else {
        delete yearCacheRef.current[yr];
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not refresh your annual review.",
      );
    } finally {
      setRefreshing(false);
    }
  };

  const doc = res?.data ?? null;
  const canRefresh =
    res?.tp_connected === true && (res.status === "ready" || res.status === "empty");
  const sortedYears = [...availableYears]
    .filter((y) => !y.is_complete || y.total_workouts == null || y.total_workouts > 0)
    .sort((a, b) => b.year - a.year);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-3 sm:p-6 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-labelledby="year-review-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl">
        {/* Pastel Sunset Header */}
        <div
          className="flex flex-wrap items-center justify-between gap-3 border-b border-orange-200/70 px-5 py-4 sm:px-6 sm:py-5"
          style={{
            backgroundImage: "linear-gradient(135deg, #FFEDD5 0%, #FCE7F3 100%)",
          }}
        >
          <div className="flex items-center gap-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-sunset text-white shadow-sm">
              <Trophy className="h-6 w-6" />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2
                  id="year-review-title"
                  className="font-display text-lg sm:text-xl font-bold text-slate-900"
                >
                  Annual Review
                </h2>
                {doc && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-white/90 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-orange-900 tabular-nums">
                    {!doc.is_complete && (
                      <span className="h-1.5 w-1.5 rounded-full bg-orange-500" />
                    )}
                    {doc.year} · {doc.is_complete ? "Completed" : "In Progress"}
                  </span>
                )}
              </div>
              <p className="text-xs sm:text-sm text-slate-700 mt-0.5 tabular-nums">
                {doc
                  ? `${formatShortDate(doc.window.start)} – ${formatShortDate(doc.window.end)} · ${doc.window.weeks} weeks${doc.is_complete ? "" : " YTD"} · ${doc.runner_name}`
                  : "Your calendar years in running — volume, main races, fitness & peaks"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {doc && res?.status === "ready" && onDiscussWithCoach && (
              <button
                type="button"
                disabled={!canDiscuss || refreshing}
                onClick={() => onDiscussWithCoach(buildDiscussYearPrompt(doc))}
                className="inline-flex items-center gap-1.5 rounded-xl border border-pink-200 bg-white/90 px-3 py-1.5 text-xs sm:text-sm font-semibold text-pink-900 shadow-2xs transition hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                <MessageSquare className="h-3.5 w-3.5 text-pink-600" />
                <span className="hidden sm:inline">Discuss with Coach</span>
                <span className="sm:hidden">Discuss</span>
              </button>
            )}

            {/* Split Refresh button: default Incremental + dropdown for Full year */}
            {canRefresh && (
              <div ref={refreshMenuRef} className="relative inline-flex">
                <button
                  type="button"
                  disabled={refreshing || loading}
                  onClick={() => void handleRefresh("incremental")}
                  title="Incremental refresh (pulls new workouts since last update)"
                  className="inline-flex items-center gap-1.5 rounded-l-xl border border-orange-200 bg-white/90 px-3 py-1.5 text-xs sm:text-sm font-semibold text-slate-800 shadow-2xs transition hover:bg-white disabled:opacity-55 cursor-pointer"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 text-orange-600 ${refreshing ? "animate-spin" : ""}`}
                  />
                  <span>{refreshing ? "Updating…" : "Refresh"}</span>
                </button>
                <button
                  type="button"
                  disabled={refreshing || loading}
                  aria-label="Refresh options"
                  aria-haspopup="menu"
                  aria-expanded={refreshMenuOpen}
                  onClick={() => setRefreshMenuOpen((prev) => !prev)}
                  className="inline-flex items-center justify-center rounded-r-xl border border-l-0 border-orange-200 bg-white/90 px-2 py-1.5 text-slate-600 shadow-2xs transition hover:bg-white hover:text-slate-900 disabled:opacity-55 cursor-pointer"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>

                {refreshMenuOpen && (
                  <div
                    role="menu"
                    aria-label="Refresh mode"
                    className="absolute right-0 top-full mt-1.5 z-30 w-60 overflow-hidden rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => void handleRefresh("incremental")}
                      className="flex w-full flex-col items-start rounded-xl px-3 py-2 text-left transition hover:bg-orange-50/70 cursor-pointer"
                    >
                      <span className="text-xs font-semibold text-slate-900">
                        Incremental refresh{" "}
                        <span className="ml-1 rounded-full bg-orange-100 px-1.5 py-0.5 text-[0.625rem] font-semibold text-orange-800">
                          Default
                        </span>
                      </span>
                      <span className="text-[0.6875rem] text-slate-500 mt-0.5">
                        Pull workouts since last update
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => void handleRefresh("full")}
                      className="flex w-full flex-col items-start rounded-xl px-3 py-2 text-left transition hover:bg-orange-50/70 cursor-pointer"
                    >
                      <span className="text-xs font-semibold text-slate-900">
                        Full year refresh
                      </span>
                      <span className="text-[0.6875rem] text-slate-500 mt-0.5">
                        Re-pull Jan 1 – Dec 31 from TrainingPeaks
                      </span>
                    </button>
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={onClose}
              aria-label="Close annual review"
              className="rounded-full border border-slate-200/80 bg-white/85 p-1.5 text-slate-500 transition hover:bg-white hover:text-slate-900 cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Multi-Year Selector Rail (Latest Year First) */}
        {sortedYears.length > 0 && (
          <div
            role="group"
            aria-label="Select calendar year"
            className="flex items-center gap-2 overflow-x-auto border-b border-slate-200 bg-white px-5 py-2.5 sm:px-6"
          >
            <span className="text-[0.6875rem] font-bold uppercase tracking-wider text-slate-400 mr-1 shrink-0">
              Year
            </span>
            {sortedYears.map((item) => {
              const isSelected = item.year === activeYear;
              return (
                <button
                  key={item.year}
                  type="button"
                  aria-pressed={isSelected}
                  disabled={refreshing}
                  onClick={() => {
                    if (item.year !== activeYear) setSelectedYear(item.year);
                  }}
                  className={`flex shrink-0 flex-col items-start rounded-xl border px-3.5 py-1.5 text-left transition tabular-nums cursor-pointer disabled:opacity-60 ${
                    isSelected
                      ? "border-transparent bg-sunset text-white shadow-sm"
                      : "border-slate-200 bg-slate-50/80 text-slate-800 hover:border-orange-300 hover:bg-orange-50/40"
                  }`}
                >
                  <span className="flex items-center gap-1.5 font-display text-sm font-bold leading-tight">
                    {item.year}
                    {!item.is_complete && (
                      <span
                        className={`rounded-full px-1.5 py-px font-sans text-[0.5625rem] font-bold uppercase ${
                          isSelected
                            ? "bg-white/25 text-white"
                            : "bg-orange-100 text-orange-800"
                        }`}
                      >
                        YTD
                      </span>
                    )}
                  </span>
                  {item.total_run_km != null && (
                    <span
                      className={`text-[0.6875rem] font-medium mt-0.5 ${
                        isSelected ? "text-white/90" : "text-slate-500"
                      }`}
                    >
                      {item.total_run_km.toLocaleString("en-US", { maximumFractionDigits: 0 })} km
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto bg-slate-50/40 p-5 sm:p-6 space-y-5">
          {loading && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <Loader2 className="h-7 w-7 animate-spin text-orange-500 mb-3" />
              <p className="font-display text-base font-semibold text-slate-800">
                Compiling your {activeYear} annual review…
              </p>
              <p className="text-xs text-slate-500 mt-1 text-center max-w-md">
                Gathering {activeYear} TrainingPeaks workouts, fitness (CTL), race events, and personal peaks
              </p>
            </div>
          )}

          {!loading && error && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 space-y-3">
              <div className="flex items-start gap-2 text-sm text-rose-800">
                <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
              <button
                type="button"
                onClick={() => void handleRefresh("incremental")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-3.5 py-1.5 text-xs font-semibold text-white cursor-pointer"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Try again
              </button>
            </div>
          )}

          {!loading && !error && res?.status === "tp_not_connected" && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50/60 p-6 space-y-3">
              <p className="font-display text-base font-bold text-slate-900">
                Connect TrainingPeaks to build your Annual Review
              </p>
              <p className="text-sm text-slate-600">
                Link your TrainingPeaks account so we can compile your calendar-year mileage, races, fitness progression, and peak efforts.
              </p>
              <button
                type="button"
                onClick={onOpenTrainingPeaks}
                className="inline-flex items-center gap-2 rounded-xl bg-sunset px-4 py-2 text-sm font-semibold text-white cursor-pointer"
              >
                <Link2 className="h-4 w-4" /> Connect TrainingPeaks
              </button>
            </div>
          )}

          {!loading && !error && res?.status === "empty" && (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center space-y-2 shadow-card">
              <Trophy className="mx-auto h-8 w-8 text-slate-300" />
              <p className="font-display text-base font-bold text-slate-900">
                No completed workouts found in {activeYear}
              </p>
              <p className="text-sm text-slate-600 max-w-md mx-auto">
                Once your TrainingPeaks calendar has completed workouts for {activeYear}, click Refresh to build your annual review.
              </p>
            </div>
          )}

          {!loading && !error && res?.status === "ready" && doc && (
            <>
              {/* 1. Hero KPI Strip */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
                  <div className="flex items-center justify-between text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
                    <span>Running Distance</span>
                    <Footprints className="h-3.5 w-3.5 text-orange-500" />
                  </div>
                  <p className="mt-2 font-display text-2xl font-bold text-slate-900 tabular-nums">
                    {doc.kpis.total_run_km.toLocaleString("en-US", { maximumFractionDigits: 0 })} km
                  </p>
                  <p className="mt-1 text-xs text-slate-500 tabular-nums">
                    {doc.kpis.avg_weekly_run_km.toFixed(1)} km/wk avg · {doc.kpis.total_runs} runs
                  </p>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
                  <div className="flex items-center justify-between text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
                    <span>Total Training Time</span>
                    <Clock className="h-3.5 w-3.5 text-pink-500" />
                  </div>
                  <p className="mt-2 font-display text-2xl font-bold text-slate-900 tabular-nums">
                    {formatHoursMinutes(doc.kpis.total_hours)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 tabular-nums">
                    {Math.round(doc.kpis.run_hours)}h run
                    {doc.kpis.bike_hours > 0 ? ` · ${Math.round(doc.kpis.bike_hours)}h bike` : ""}
                    {doc.kpis.strength_hours > 0 ? ` · ${Math.round(doc.kpis.strength_hours)}h S&C` : ""}
                  </p>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
                  <div className="flex items-center justify-between text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
                    <span>Fitness (CTL)</span>
                    <TrendingUp className="h-3.5 w-3.5 text-violet-600" />
                  </div>
                  <div className="mt-2 flex flex-wrap items-baseline gap-2">
                    <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
                      {doc.kpis.ctl_start != null && doc.kpis.ctl_end != null
                        ? `${Math.round(doc.kpis.ctl_start)} → ${Math.round(doc.kpis.ctl_end)}`
                        : doc.kpis.ctl_end != null
                          ? Math.round(doc.kpis.ctl_end)
                          : "—"}
                    </span>
                    {doc.kpis.ctl_delta != null && (
                      <StatusBadge
                        tone={
                          doc.kpis.ctl_delta > 0
                            ? "emerald"
                            : doc.kpis.ctl_delta < 0
                              ? "amber"
                              : "slate"
                        }
                        direction={
                          doc.kpis.ctl_delta > 0
                            ? "up"
                            : doc.kpis.ctl_delta < 0
                              ? "down"
                              : "flat"
                        }
                        size="sm"
                        className="tabular-nums"
                        label={`${doc.kpis.ctl_delta > 0 ? "+" : ""}${Math.round(doc.kpis.ctl_delta)}${
                          doc.kpis.ctl_delta_pct != null
                            ? ` (${doc.kpis.ctl_delta_pct > 0 ? "+" : ""}${doc.kpis.ctl_delta_pct}%)`
                            : ""
                        }`}
                      />
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-500 tabular-nums">
                    {doc.kpis.ctl_peak != null
                      ? `Peak ${Math.round(doc.kpis.ctl_peak)}${doc.kpis.ctl_peak_date ? ` (${formatShortDate(doc.kpis.ctl_peak_date).replace(/, \d{4}$/, "")})` : ""} · `
                      : ""}
                    {doc.kpis.total_tss.toLocaleString("en-US")} TSS
                  </p>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
                  <div className="flex items-center justify-between text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
                    <span>Consistency{doc.is_complete ? "" : " (YTD)"}</span>
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                  </div>
                  <div className="mt-2 flex items-baseline gap-1.5">
                    <span className="font-display text-2xl font-bold text-slate-900 tabular-nums">
                      {doc.kpis.active_weeks} / {doc.kpis.total_weeks}
                    </span>
                    <span className="text-xs font-semibold text-slate-500 tabular-nums">
                      wks ({doc.kpis.active_weeks_pct}%)
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500 tabular-nums">
                    {doc.kpis.longest_streak_weeks}-wk streak
                    {doc.kpis.peak_week_km != null ? ` · Peak wk ${doc.kpis.peak_week_km.toFixed(1)} km` : ""}
                  </p>
                </div>
              </div>

              {/* 2. Flagship Calendar-Year Volume & CTL Chart */}
              <Suspense
                fallback={
                  <div className="h-72 rounded-2xl border border-slate-200 animate-shimmer" />
                }
              >
                <YearReviewChart year={doc.year} monthly={doc.monthly} weekly={doc.weekly} />
              </Suspense>

              {/* 3. Main Races */}
              <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Trophy className="h-4 w-4 text-orange-500" />
                    <h3 className="font-display text-base font-bold text-slate-900">
                      Main Races ({doc.year})
                    </h3>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-slate-600 tabular-nums">
                      {doc.races.length} {doc.races.length === 1 ? "race" : "races"}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500">
                    From TrainingPeaks Events, race-tagged workouts &amp; your Goal Plan
                  </span>
                </div>

                {doc.races.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {doc.races.map((race) => (
                      <RaceCard key={`${race.date}-${race.workout_id ?? race.name}`} race={race} />
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 py-5 text-center text-xs text-slate-600">
                    No races logged in {doc.year} — add TrainingPeaks Events or tag workouts with <code className="font-semibold">race</code> to highlight them here.
                  </div>
                )}
              </section>

              {/* 4. Fitness & Recovery Shift + Year Peak Performances */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Fitness Shift */}
                <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card flex flex-col justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Activity className="h-4 w-4 text-violet-600" />
                      <div>
                        <h3 className="font-display text-sm font-bold text-slate-900">
                          Fitness &amp; Recovery Shift ({doc.year})
                        </h3>
                        <p className="text-xs text-slate-500">
                          Early {doc.year} vs {doc.is_complete ? `late ${doc.year}` : "latest"} (8-week averages)
                        </p>
                      </div>
                    </div>

                    {doc.fitness_shift.length > 0 ? (
                      <div className="divide-y divide-slate-100 tabular-nums">
                        {doc.fitness_shift.map((item) => {
                          const tone =
                            item.verdict === "improving"
                              ? ("emerald" as const)
                              : item.verdict === "declining"
                                ? ("rose" as const)
                                : ("slate" as const);
                          const badgeLabel =
                            item.verdict === "improving"
                              ? item.key === "weekly_km"
                                ? "Building"
                                : "Improving"
                              : item.verdict === "declining"
                                ? "Declining"
                                : "Stable";
                          return (
                            <div
                              key={item.key}
                              className="grid grid-cols-12 items-center gap-2 py-2.5 text-xs"
                            >
                              <span className="col-span-4 font-semibold text-slate-700">
                                {item.label}
                              </span>
                              <span className="col-span-4 text-slate-500">
                                {item.start} →{" "}
                                <strong className="text-slate-900">{item.latest}</strong>
                              </span>
                              <span
                                className={`col-span-2 text-right font-bold ${
                                  tone === "emerald"
                                    ? "text-emerald-700"
                                    : tone === "rose"
                                      ? "text-rose-600"
                                      : "text-slate-600"
                                }`}
                              >
                                {item.delta}
                              </span>
                              <div className="col-span-2 flex justify-end">
                                <StatusBadge
                                  tone={tone}
                                  direction={directionFromArrow(item.arrow)}
                                  label={badgeLabel}
                                  size="sm"
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500 py-4">
                        Not enough multi-month health or threshold data in {doc.year} to calculate a shift.
                      </p>
                    )}
                  </div>

                  {doc.coverage.analyzed_runs > 0 && (
                    <p className="text-[0.6875rem] text-slate-500">
                      Threshold paces fitted from {doc.coverage.analyzed_runs} analyzed runs in your training log
                      {doc.coverage.training_log_start
                        ? ` (${formatShortDate(doc.coverage.training_log_start)} – ${formatShortDate(doc.coverage.training_log_end)})`
                        : ""}
                      .
                    </p>
                  )}
                </section>

                {/* Year Peak Performances & Milestones */}
                <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card flex flex-col justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Award className="h-4 w-4 text-amber-500" />
                      <div>
                        <h3 className="font-display text-sm font-bold text-slate-900">
                          {doc.year} Peak Performances
                        </h3>
                        <p className="text-xs text-slate-500">
                          Fastest {doc.year} TrainingPeaks efforts · PRs from your profile
                        </p>
                      </div>
                    </div>

                    {doc.peaks.length > 0 ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-left text-xs tabular-nums">
                          <thead>
                            <tr className="text-[0.6875rem] uppercase tracking-wider text-slate-500">
                              <th className="pb-2 pr-2 font-semibold">Distance</th>
                              <th className="pb-2 pr-2 font-semibold">Best Time</th>
                              <th className="pb-2 pr-2 font-semibold">Pace</th>
                              <th className="pb-2 pr-2 font-semibold">Date</th>
                              <th className="pb-2 text-right font-semibold">Profile PR</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {doc.peaks.map((pk) => (
                              <tr key={pk.pr_type} title={pk.workout_title ?? undefined}>
                                <td className="py-2 pr-2 font-bold text-slate-900 whitespace-nowrap">
                                  {pk.distance}
                                </td>
                                <td className="py-2 pr-2 font-display font-bold text-slate-900 whitespace-nowrap">
                                  {pk.time}
                                </td>
                                <td className="py-2 pr-2 text-slate-700 whitespace-nowrap">
                                  {pk.pace}
                                </td>
                                <td className="py-2 pr-2 text-slate-500 whitespace-nowrap">
                                  {pk.date
                                    ? formatShortDate(pk.date).replace(/, \d{4}$/, "")
                                    : "—"}
                                </td>
                                <td className="py-2 text-right whitespace-nowrap">
                                  {pk.all_time_pr ? (
                                    <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[0.6875rem] font-semibold text-amber-800">
                                      ★ Profile PR
                                    </span>
                                  ) : pk.profile_pr_time ? (
                                    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[0.6875rem] font-medium text-slate-600">
                                      PR {pk.profile_pr_time}
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[0.6875rem] font-medium text-slate-600">
                                      Year Best
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500 py-3">
                        No TrainingPeaks distance peaks recorded in {doc.year}.
                      </p>
                    )}
                  </div>

                  {(doc.milestones.longest_run ||
                    doc.milestones.peak_week ||
                    doc.milestones.peak_month) && (
                    <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3 tabular-nums">
                      {doc.milestones.longest_run && (
                        <span className="rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1 text-[0.6875rem] text-slate-600">
                          Longest Run:{" "}
                          <strong className="text-slate-900">
                            {doc.milestones.longest_run.km.toFixed(1)} km
                          </strong>{" "}
                          ({formatShortDate(doc.milestones.longest_run.date).replace(/, \d{4}$/, "")})
                        </span>
                      )}
                      {doc.milestones.peak_week && (
                        <span className="rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1 text-[0.6875rem] text-slate-600">
                          Peak Week:{" "}
                          <strong className="text-slate-900">
                            {doc.milestones.peak_week.km.toFixed(1)} km
                          </strong>{" "}
                          ({formatShortDate(doc.milestones.peak_week.date).replace(/, \d{4}$/, "")})
                        </span>
                      )}
                      {doc.milestones.peak_month && (
                        <span className="rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1 text-[0.6875rem] text-slate-600">
                          Peak Month:{" "}
                          <strong className="text-slate-900">
                            {doc.milestones.peak_month.km.toFixed(0)} km
                          </strong>{" "}
                          ({doc.milestones.peak_month.label})
                        </span>
                      )}
                    </div>
                  )}
                </section>
              </div>

              {/* 5. Sport & Run Mix + Calendar-Year Activity Heatmap */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                <section className="lg:col-span-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card flex flex-col justify-between gap-3">
                  <div>
                    <h3 className="font-display text-sm font-bold text-slate-900">
                      Sport &amp; Run Mix
                    </h3>
                    <p className="text-xs text-slate-500">
                      {doc.kpis.total_workouts} completed sessions in {doc.year}
                    </p>

                    {doc.mix.sports.length > 0 && (
                      <>
                        <div className="mt-3 flex h-3.5 w-full overflow-hidden rounded-full bg-slate-100 gap-0.5">
                          {doc.mix.sports.map((s) => (
                            <div
                              key={s.key}
                              style={{ width: `${Math.max(2, s.pct)}%` }}
                              className={`h-full ${SPORT_COLORS[s.key]?.bar ?? "bg-slate-400"}`}
                              title={`${s.label}: ${s.hours}h (${s.pct}%)`}
                            />
                          ))}
                        </div>

                        <div className="mt-3 space-y-1.5 text-xs tabular-nums">
                          {doc.mix.sports.map((s) => (
                            <div key={s.key} className="flex items-center justify-between gap-2">
                              <span className="inline-flex items-center gap-1.5 font-semibold text-slate-800">
                                <span
                                  className={`h-2 w-2 rounded-full ${SPORT_COLORS[s.key]?.dot ?? "bg-slate-400"}`}
                                />
                                {s.label}
                              </span>
                              <span className="text-slate-600">
                                <strong className="text-slate-900">{Math.round(s.hours)}h</strong> (
                                {s.pct}%) · {s.sessions}
                              </span>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>

                  {doc.kpis.total_runs > 0 && (
                    <div className="flex flex-wrap gap-1.5 border-t border-slate-100 pt-3 tabular-nums">
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-slate-700">
                        {doc.mix.run_breakdown.easy_pct}% Easy
                      </span>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-slate-700">
                        {doc.mix.run_breakdown.quality_pct}% Quality
                      </span>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-semibold text-slate-700">
                        {doc.mix.run_breakdown.long_race_pct}% Long &amp; Race
                      </span>
                    </div>
                  )}
                </section>

                <div className="lg:col-span-7">
                  <ActivityHeatmap
                    year={doc.year}
                    isComplete={doc.is_complete}
                    heatmap={doc.heatmap}
                  />
                </div>
              </div>

              {/* Clean Footer */}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-xs text-slate-600 tabular-nums">
                <span>
                  <strong className="text-slate-800">Calendar Year {doc.year}</strong> (
                  {formatShortDate(doc.window.start)} – {formatShortDate(doc.window.end)}
                  {doc.is_complete ? "" : ", in progress"})
                </span>
                <span>Updated {formatShortDate(doc.as_of_date)}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
