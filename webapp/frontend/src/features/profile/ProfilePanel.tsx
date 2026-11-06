import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Compass,
  Flag,
  Footprints,
  HeartPulse,
  Link2,
  Loader2,
  MapPin,
  Pencil,
  ShieldCheck,
  Trophy,
  X,
} from "lucide-react";
import { fetchProfile, updateProfile } from "../../shared/api";
import { formatShortDate } from "../../shared/format";
import type {
  ProfileResponse,
  ProfileUpdatePayload,
  SubGoal,
} from "../../shared/types";
import { ProfileForm } from "./ProfileForm";

interface ProfilePanelProps {
  open: boolean;
  initialMode: "view" | "edit";
  email: string;
  initials: string;
  onClose: () => void;
  onOpenTrainingPeaks: () => void;
  onProfileUpdated: (res: ProfileResponse) => void;
}

export function ProfilePanel({
  open,
  initialMode,
  email,
  initials,
  onClose,
  onOpenTrainingPeaks,
  onProfileUpdated,
}: ProfilePanelProps) {
  const [mode, setMode] = useState<"view" | "edit">(initialMode);
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMode(initialMode);
  }, [initialMode, open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchProfile()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Could not load runner profile.",
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

  const handleSave = async (payload: ProfileUpdatePayload) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProfile(payload);
      setData(updated);
      setMode("view");
      onProfileUpdated(updated);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save profile updates.",
      );
    } finally {
      setSaving(false);
    }
  };

  const profile = data?.profile;
  const fullName = profile
    ? `${profile.firstname ?? ""} ${profile.lastname ?? ""}`.trim() || email
    : email;
  const todayIso = new Date().toISOString().slice(0, 10);

  const findActiveSubGoalIndex = (subGoals: SubGoal[]): number => {
    for (let i = 0; i < subGoals.length; i += 1) {
      if ((subGoals[i].race_date || "") >= todayIso) {
        return i;
      }
    }
    return -1;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/35 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-drawer-title"
    >
      <div className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl border-l border-slate-200">
        {/* Pastel Header */}
        <div
          className="flex items-start justify-between border-b border-orange-200/70 px-6 py-5"
          style={{
            backgroundImage: "linear-gradient(135deg, #FFEDD5 0%, #FCE7F3 100%)",
          }}
        >
          <div className="flex items-center gap-3.5">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sunset font-display text-base font-bold text-white shadow-sm">
              {initials}
            </span>
            <div>
              <h2
                id="profile-drawer-title"
                className="font-display text-lg font-bold text-slate-900"
              >
                {fullName}
              </h2>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600 mt-0.5">
                <span className="inline-flex items-center gap-1">
                  <ShieldCheck className="h-3.5 w-3.5 text-orange-500" />
                  {profile?.email || email}
                </span>
                {profile?.location && (
                  <span className="inline-flex items-center gap-1 text-slate-500">
                    · <MapPin className="h-3 w-3" /> {profile.location}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {mode === "view" && profile && (
              <button
                type="button"
                onClick={() => setMode("edit")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-sunset bg-sunset-hover px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs transition cursor-pointer"
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close profile drawer"
              className="rounded-full bg-white/80 p-1.5 text-slate-500 transition hover:bg-white hover:text-slate-900 cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <Loader2 className="h-6 w-6 animate-spin text-orange-500 mb-2" />
              <p className="text-xs font-medium">Loading runner profile…</p>
            </div>
          )}

          {!loading && error && mode === "view" && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800">
              {error}
            </div>
          )}

          {!loading && profile && mode === "edit" && (
            <ProfileForm
              profile={profile}
              email={email}
              saving={saving}
              error={error}
              onCancel={() => {
                setError(null);
                setMode("view");
              }}
              onSave={handleSave}
            />
          )}

          {!loading && profile && mode === "view" && (
            <div className="space-y-6">
              {/* Biometrics Strip */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Age", value: profile.age || "—" },
                  { label: "Height", value: profile.height || "—" },
                  { label: "Weight", value: profile.weight || "—" },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="rounded-2xl border border-slate-200 bg-slate-50/60 px-4 py-3"
                  >
                    <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                      {stat.label}
                    </p>
                    <p className="mt-1 font-display text-base font-bold text-slate-900 tabular-nums">
                      {stat.value}
                    </p>
                  </div>
                ))}
              </div>

              {/* Goal Roadmap */}
              <div className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {profile.goal_type === "plan" && profile.north_star
                    ? "Goal Plan Roadmap"
                    : "Active Training Goal"}
                </h3>

                {profile.goal_type === "plan" && profile.north_star ? (
                  <div className="space-y-3">
                    {(() => {
                      const subs = profile.sub_goals || [];
                      const activeIdx = findActiveSubGoalIndex(subs);
                      return subs.map((sg, idx) => {
                        const isCompleted =
                          Boolean(sg.result) ||
                          (activeIdx === -1
                            ? (sg.race_date || "") < todayIso
                            : idx < activeIdx);
                        const isActive = idx === activeIdx;

                        return (
                          <div
                            key={`${sg.goal}-${sg.race_date}-${idx}`}
                            className={`rounded-2xl border p-4 transition ${
                              isActive
                                ? "border-rose-300 bg-rose-50/80 shadow-xs"
                                : isCompleted
                                  ? "border-emerald-200 bg-emerald-50/30"
                                  : "border-slate-200 bg-white"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <Flag
                                  className={`h-4 w-4 shrink-0 ${
                                    isActive
                                      ? "text-rose-700"
                                      : isCompleted
                                        ? "text-emerald-600"
                                        : "text-slate-400"
                                  }`}
                                />
                                <div>
                                  <p className="text-sm font-bold text-slate-900">
                                    {sg.goal}
                                  </p>
                                  {sg.race_name && (
                                    <p className="text-xs text-slate-600">
                                      {sg.race_name}
                                    </p>
                                  )}
                                </div>
                              </div>
                              {isActive && (
                                <span className="rounded-full bg-sunset px-2.5 py-0.5 text-[11px] font-semibold text-white">
                                  Active Block
                                </span>
                              )}
                              {isCompleted && !isActive && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700 border border-emerald-200">
                                  <CheckCircle2 className="h-3 w-3" /> Completed
                                </span>
                              )}
                            </div>
                            <p className="mt-2 text-xs text-slate-500">
                              {formatShortDate(sg.start_date)} →{" "}
                              <strong className="text-slate-700">
                                {formatShortDate(sg.race_date)}
                              </strong>
                              {sg.taper_weeks != null
                                ? ` · ${sg.taper_weeks}w taper`
                                : ""}
                            </p>
                            {sg.result && (
                              <p className="mt-2 rounded-xl bg-white/90 px-3 py-1.5 text-xs font-medium text-emerald-800 border border-emerald-200/70">
                                Result: {sg.result}
                              </p>
                            )}
                          </div>
                        );
                      });
                    })()}

                    {/* North Star Card */}
                    <div
                      className="rounded-2xl border border-violet-300 p-4"
                      style={{
                        backgroundImage:
                          "linear-gradient(135deg, #EDE9FE 0%, #E0F2FE 100%)",
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <Compass className="h-4 w-4 text-violet-700 shrink-0" />
                          <div>
                            <p className="font-display text-sm font-bold text-slate-900">
                              {profile.north_star.goal}
                            </p>
                            {profile.north_star.race_name && (
                              <p className="text-xs text-slate-700">
                                {profile.north_star.race_name}
                              </p>
                            )}
                          </div>
                        </div>
                        <span className="rounded-full bg-white/90 px-2.5 py-0.5 text-[11px] font-semibold text-violet-800 border border-violet-300">
                          North Star
                        </span>
                      </div>
                      <p className="mt-2 text-xs text-slate-700">
                        Race day:{" "}
                        <strong>
                          {formatShortDate(profile.north_star.race_date)}
                        </strong>
                        {profile.north_star.taper_weeks != null
                          ? ` · ${profile.north_star.taper_weeks}w taper`
                          : ""}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-rose-300 bg-rose-50/80 p-4">
                    <div className="flex items-center gap-2">
                      <Trophy className="h-4 w-4 text-rose-700" />
                      <p className="font-display text-sm font-bold text-slate-900">
                        {profile.training_goal || "No active goal set"}
                      </p>
                    </div>
                    <p className="mt-1.5 text-xs text-slate-600">
                      Target date:{" "}
                      <strong className="text-slate-800">
                        {formatShortDate(profile.timeline)}
                      </strong>
                      {profile.taper_weeks != null
                        ? ` · ${profile.taper_weeks}w taper`
                        : ""}
                    </p>
                  </div>
                )}
              </div>

              {/* Context Cards */}
              <div className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Coaching Context
                </h3>

                {[
                  {
                    icon: Trophy,
                    title: "Recent Race Times",
                    value: profile.recent_race_times,
                  },
                  {
                    icon: HeartPulse,
                    title: "Injuries & Watchpoints",
                    value: profile.injuries,
                  },
                  {
                    icon: CheckCircle2,
                    title: "Cross-Training & Strength",
                    value: profile.cross_training_strength,
                  },
                  {
                    icon: Footprints,
                    title: "Shoe Rotation",
                    value: profile.shoe_rotation,
                  },
                ].map((item) => {
                  const Icon = item.icon;
                  return (
                    <div
                      key={item.title}
                      className="rounded-2xl border border-slate-200 bg-white p-3.5"
                    >
                      <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
                        <Icon className="h-3.5 w-3.5 text-rose-700" />
                        <span>{item.title}</span>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-slate-600">
                        {item.value || "Not specified yet"}
                      </p>
                    </div>
                  );
                })}
              </div>

              {/* TrainingPeaks Credential Card */}
              <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-800 text-white">
                    <Link2 className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-xs font-semibold text-slate-900">
                      TrainingPeaks Telemetry
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {data?.tp.connected
                        ? `Connected${data.tp.tp_athlete_id ? ` · Athlete #${data.tp.tp_athlete_id}` : ""}`
                        : "Not connected"}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={onOpenTrainingPeaks}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 cursor-pointer"
                >
                  {data?.tp.connected ? "Replace cookie" : "Connect"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
