import { useEffect, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  Compass,
  Flag,
  Info,
  Link2,
  Loader2,
  Pencil,
  RefreshCw,
  Timer,
  TrendingDown,
  Trophy,
  X,
  XCircle,
} from "lucide-react";
import { fetchRacePredictor, refreshRacePredictor } from "../../shared/api";
import {
  extractLeadingStatus,
  formatDuration,
  formatShortDate,
  formatSignedGap,
} from "../../shared/format";
import { StatusBadge } from "../../shared/RichMarkdown";
import type {
  CheckinDriver,
  RacePredictorActiveGoal,
  RacePredictorResponse,
} from "../../shared/types";

interface RacePredictorPanelProps {
  open: boolean;
  onClose: () => void;
  onSetGoalInProfile: () => void;
  onBuildPlan: () => void;
  onOpenTrainingPeaks: () => void;
}

function ImpliedDriverCell({ text }: { text: string }) {
  const status = text ? extractLeadingStatus(text) : null;
  if (!status || status.restText) return <>{text}</>;
  return (
    <StatusBadge
      tone={status.tone}
      icon={status.icon}
      label={status.badgeText}
      size="sm"
    />
  );
}

function goalKindBadge(goal: RacePredictorActiveGoal): {
  label: string;
  subgoal: boolean;
} {
  if (goal.kind === "sub_goal") {
    const step =
      goal.sub_goal_step && goal.sub_goal_total
        ? `Sub-Goal ${goal.sub_goal_step} of ${goal.sub_goal_total}`
        : "Active Sub-Goal";
    return { label: `${step} · Working Towards`, subgoal: true };
  }
  if (goal.kind === "north_star") {
    return { label: "North Star Block", subgoal: false };
  }
  return { label: "Target Race Goal", subgoal: false };
}

function DriverTable({ drivers }: { drivers: CheckinDriver[] }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        12-Week Key-Session Drivers
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wider text-slate-500">
              <th className="py-1.5 pr-3 font-semibold">Driver</th>
              <th className="py-1.5 pr-3 font-semibold">Evidence</th>
              <th className="py-1.5 font-semibold">Implied</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {drivers.map((d) => (
              <tr key={d.driver}>
                <td className="py-2 pr-3 font-semibold text-slate-900 whitespace-nowrap align-top">
                  {d.driver}
                </td>
                <td className="py-2 pr-3 text-slate-600 align-top">
                  {d.evidence}
                </td>
                <td className="py-2 text-slate-700 tabular-nums whitespace-nowrap align-top">
                  <ImpliedDriverCell text={d.implied} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RacePredictorPanel({
  open,
  onClose,
  onSetGoalInProfile,
  onBuildPlan,
  onOpenTrainingPeaks,
}: RacePredictorPanelProps) {
  const [res, setRes] = useState<RacePredictorResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRacePredictor()
      .then((data) => {
        if (!cancelled) setRes(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not load your race projection.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const handleRefresh = async () => {
    if (refreshing || loading) return;
    setRefreshing(true);
    setError(null);
    try {
      const updated = await refreshRacePredictor();
      setRes(updated);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not refresh your race projection.",
      );
    } finally {
      setRefreshing(false);
    }
  };

  const doc = res?.data ?? null;
  const activeGoal = doc?.active_goal ?? res?.active_goal ?? null;
  const projection = doc?.projection ?? null;
  const northStar = doc?.north_star ?? null;
  const canRefresh =
    res?.tp_connected === true &&
    (res.status === "ready" || res.status === "insufficient_data");

  const gapInfo = formatSignedGap(projection?.gap_s);
  const gapTone =
    gapInfo.tone === "positive"
      ? ("emerald" as const)
      : gapInfo.tone === "warning"
        ? ("amber" as const)
        : gapInfo.tone === "danger"
          ? ("rose" as const)
          : ("slate" as const);
  const gapIcon =
    gapTone === "emerald"
      ? CheckCircle2
      : gapTone === "amber"
        ? TrendingDown
        : gapTone === "rose"
          ? XCircle
          : Info;

  const confTone =
    projection?.confidence === "High"
      ? ("emerald" as const)
      : projection?.confidence === "Medium"
        ? ("amber" as const)
        : ("slate" as const);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/35 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-labelledby="race-predictor-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl border-l border-slate-200">
        {/* Header */}
        <div
          className="flex items-start justify-between border-b border-orange-200/70 px-6 py-5"
          style={{
            backgroundImage: "linear-gradient(135deg, #FFEDD5 0%, #FCE7F3 100%)",
          }}
        >
          <div className="flex items-center gap-3.5">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sunset text-white shadow-sm">
              <Timer className="h-6 w-6" />
            </span>
            <div>
              <h2
                id="race-predictor-title"
                className="font-display text-lg font-bold text-slate-900"
              >
                Race Predictor
              </h2>
              <p className="text-sm text-slate-700 mt-0.5">
                Based on your last 12 weeks of key sessions
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {canRefresh && (
              <button
                type="button"
                disabled={refreshing || loading}
                onClick={() => void handleRefresh()}
                className="inline-flex items-center gap-1.5 rounded-xl bg-white/90 px-3 py-1.5 text-sm font-semibold text-slate-800 border border-orange-200 shadow-2xs transition hover:bg-white disabled:opacity-55 cursor-pointer"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${refreshing ? "animate-spin text-orange-600" : "text-orange-600"}`}
                />
                <span>{refreshing ? "Updating…" : "Refresh"}</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close race predictor"
              className="rounded-full bg-white/80 p-1.5 text-slate-500 transition hover:bg-white hover:text-slate-900 cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {loading && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <Loader2 className="h-6 w-6 animate-spin text-orange-500 mb-2.5" />
              <p className="font-display text-sm font-semibold text-slate-800">
                Loading 12-week race projection…
              </p>
              <p className="text-xs text-slate-500 mt-1">
                Checking threshold, race-pace, HR efficiency &amp; durability signals
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
                onClick={() => void handleRefresh()}
                className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-3.5 py-1.5 text-xs font-semibold text-white cursor-pointer"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Try again
              </button>
            </div>
          )}

          {/* No Goal State */}
          {!loading && !error && res?.status === "no_goal" && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5 space-y-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500 text-white shadow-2xs">
                  <Flag className="h-5 w-5" />
                </span>
                <div>
                  <h3 className="font-display text-base font-bold text-slate-900">
                    {res.reason === "race_passed"
                      ? "Your previous goal race has passed"
                      : res.reason === "non_race_goal"
                        ? "Set a distance race goal to unlock predictions"
                        : "No active race goal set"}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-slate-700">
                    First set a race goal (or sub-goal roadmap) in your Profile,
                    and then build a training plan with your coach.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-xl border border-amber-200/80 bg-white p-3.5">
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-700">
                    Step 1
                  </p>
                  <p className="mt-1 font-display text-sm font-bold text-slate-900">
                    Set a Goal in Profile
                  </p>
                  <p className="mt-0.5 text-xs text-slate-600">
                    Choose a target race distance (5K to Marathon) or stepping-stone sub-goals.
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white/80 p-3.5">
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
                    Step 2
                  </p>
                  <p className="mt-1 font-display text-sm font-bold text-slate-900">
                    Build a Training Plan
                  </p>
                  <p className="mt-0.5 text-xs text-slate-600">
                    Structure your weekly key sessions toward race day.
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2.5 pt-1">
                <button
                  type="button"
                  onClick={onSetGoalInProfile}
                  className="inline-flex items-center gap-2 rounded-xl bg-sunset bg-sunset-hover px-4 py-2.5 text-sm font-semibold text-white shadow-xs transition cursor-pointer"
                >
                  <Pencil className="h-4 w-4" />
                  Set Goal in Profile
                </button>
                <button
                  type="button"
                  onClick={onBuildPlan}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 transition hover:bg-slate-50 cursor-pointer"
                >
                  <CalendarRange className="h-4 w-4 text-amber-600" />
                  Build Plan
                </button>
              </div>
            </div>
          )}

          {/* TP Not Connected State */}
          {!loading && !error && res?.status === "tp_not_connected" && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50/60 p-5 space-y-3">
              <p className="font-display text-base font-bold text-slate-900">
                Connect TrainingPeaks to calculate your race projection
              </p>
              <p className="text-sm text-slate-600">
                Link your TrainingPeaks account so your last 12 weeks of key workouts can be analyzed.
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

          {/* Active Goal Context Card (shown for ready & insufficient_data) */}
          {!loading &&
            !error &&
            activeGoal &&
            (res?.status === "ready" || res?.status === "insufficient_data") && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-4 space-y-2.5">
                {(() => {
                  const badge = goalKindBadge(activeGoal);
                  return (
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex items-start gap-2.5">
                        {badge.subgoal ? (
                          <Flag className="h-4 w-4 text-rose-700 shrink-0 mt-1" />
                        ) : (
                          <Trophy className="h-4 w-4 text-rose-700 shrink-0 mt-1" />
                        )}
                        <div>
                          <span className="inline-block rounded-full bg-white/90 px-2.5 py-0.5 text-xs font-semibold text-rose-800 border border-rose-200">
                            {badge.label}
                          </span>
                          <h3 className="mt-1 font-display text-lg font-bold text-slate-900">
                            {activeGoal.training_goal}
                          </h3>
                          {activeGoal.race_name && (
                            <p className="text-sm text-slate-700">
                              {activeGoal.race_name}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="text-right text-sm text-slate-700">
                        {activeGoal.race_date && (
                          <p className="font-semibold text-slate-900">
                            {formatShortDate(activeGoal.race_date)}
                          </p>
                        )}
                        {activeGoal.weeks_remaining != null && (
                          <p className="text-xs text-slate-600">
                            {activeGoal.weeks_remaining} weeks to race day
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {activeGoal.planned === false && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200/80 bg-white/90 px-3 py-2 text-xs text-slate-700">
                    <span>
                      This block does not have a structured plan in TrainingPeaks yet.
                    </span>
                    <button
                      type="button"
                      onClick={onBuildPlan}
                      className="inline-flex items-center gap-1 font-semibold text-orange-700 hover:text-orange-900 cursor-pointer"
                    >
                      <CalendarRange className="h-3.5 w-3.5" />
                      Build Plan
                    </button>
                  </div>
                )}
              </div>
            )}

          {/* Insufficient Data State */}
          {!loading && !error && res?.status === "insufficient_data" && (
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 space-y-2">
              <div className="flex items-center gap-2 text-slate-800">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <p className="font-display text-base font-bold">
                  Not enough key-session data yet
                </p>
              </div>
              <p className="text-sm text-slate-600 leading-relaxed">
                Complete and analyze a threshold, race-pace, steady, or benchmark
                run in TrainingPeaks over the last 12 weeks to unlock your finish
                time projection.
              </p>
            </div>
          )}

          {/* Ready Projection Hero + North Star + Drivers */}
          {!loading &&
            !error &&
            res?.status === "ready" &&
            projection &&
            projection.race_day_s != null && (
              <>
                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                        Projected Race-Day Finish ({projection.goal_label})
                      </p>
                      <div className="mt-1 flex flex-wrap items-baseline gap-2.5">
                        <span className="font-display text-3xl sm:text-4xl font-bold text-slate-900 tabular-nums">
                          {formatDuration(projection.race_day_s)}
                        </span>
                        {projection.race_pace_s_per_km != null && (
                          <span className="text-base font-semibold text-slate-600 tabular-nums">
                            {formatDuration(
                              Math.round(projection.race_pace_s_per_km),
                            )}
                            /km
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {projection.confidence && (
                        <StatusBadge
                          tone={confTone}
                          icon={confTone === "emerald" ? CheckCircle2 : Info}
                          label={`${projection.confidence} confidence`}
                          size="sm"
                        />
                      )}
                      {projection.stale && (
                        <StatusBadge
                          tone="amber"
                          icon={AlertTriangle}
                          label="Stale evidence"
                          size="sm"
                        />
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2.5">
                    <StatusBadge
                      tone={gapTone}
                      label={gapInfo.label}
                      icon={gapIcon}
                    />
                    {projection.goal_s != null && (
                      <span className="text-sm text-slate-600 tabular-nums">
                        Goal:{" "}
                        <strong className="text-slate-900">
                          {formatDuration(projection.goal_s)}
                        </strong>
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3 border-t border-slate-100 pt-3.5">
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                        Today&apos;s Fitness Equivalent
                      </p>
                      <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                        {projection.today_s != null
                          ? formatDuration(projection.today_s)
                          : "—"}
                        {projection.today_pace_s_per_km != null && (
                          <span className="ml-1.5 text-xs font-normal text-slate-500">
                            (
                            {formatDuration(
                              Math.round(projection.today_pace_s_per_km),
                            )}
                            /km)
                          </span>
                        )}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                        Signal Range
                      </p>
                      <p className="mt-0.5 font-display text-lg font-bold text-slate-900 tabular-nums">
                        {projection.range_s
                          ? `${formatDuration(projection.range_s[0])} – ${formatDuration(projection.range_s[1])}`
                          : "—"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* North Star Equivalent (when working towards a Sub-Goal) */}
                {northStar && northStar.equivalent_s != null && (
                  <div
                    className="rounded-2xl border border-violet-200 p-4 space-y-1.5"
                    style={{
                      backgroundImage:
                        "linear-gradient(135deg, #EDE9FE 0%, #E0F2FE 100%)",
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-violet-800">
                        <Compass className="h-3.5 w-3.5 text-violet-700" />
                        North Star Equivalent · {northStar.training_goal}
                      </span>
                      {northStar.race_date && (
                        <span className="text-xs font-medium text-slate-600">
                          {formatShortDate(northStar.race_date)}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-baseline gap-2.5">
                      <span className="font-display text-xl font-bold text-slate-900 tabular-nums">
                        {formatDuration(northStar.equivalent_s)}
                      </span>
                      {northStar.target_s != null && (
                        <span className="text-sm text-slate-700 tabular-nums">
                          vs target {formatDuration(northStar.target_s)}
                        </span>
                      )}
                      {northStar.gap_s != null && (
                        <span className="text-xs font-semibold text-violet-900 tabular-nums">
                          ({formatSignedGap(northStar.gap_s).label})
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {projection.drivers && projection.drivers.length > 0 && (
                  <DriverTable drivers={projection.drivers} />
                )}

                {/* Provenance Footer */}
                {doc && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-xs text-slate-600 space-y-0.5">
                    <p>
                      <strong className="text-slate-800">
                        {doc.window_weeks}-week window
                      </strong>{" "}
                      · {doc.key_sessions_count} key session
                      {doc.key_sessions_count === 1 ? "" : "s"} analyzed · as of{" "}
                      {formatShortDate(doc.as_of_date)}
                    </p>
                    {doc.trigger_workout && (
                      <p className="text-slate-500">
                        Auto-updated after analyzing &ldquo;
                        {doc.trigger_workout.title}&rdquo; (
                        {doc.trigger_workout.quality_km} quality km on{" "}
                        {formatShortDate(doc.trigger_workout.date)})
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
        </div>
      </div>
    </div>
  );
}
