import { useState } from "react";
import {
  AlertCircle,
  Compass,
  Flag,
  Loader2,
  Lock,
  Plus,
  Trash2,
} from "lucide-react";
import type { ProfileUpdatePayload, RunnerProfile } from "../../shared/types";
import { PersonalRecordsFields } from "./PersonalRecordsFields";
import { ShoeRotationFields } from "./ShoeRotationFields";
import {
  toEditablePersonalRecords,
  toEditableShoeRotation,
  toPersonalRecordsPayload,
  toShoeRotationPayload,
  validatePersonalRecords,
} from "./performanceGear";

interface ProfileFormProps {
  profile: RunnerProfile;
  email: string;
  saving: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (payload: ProfileUpdatePayload) => Promise<void>;
}

interface EditableSubGoal {
  goal: string;
  race_name: string;
  start_date: string;
  race_date: string;
  taper_weeks: string;
  savedResult?: string | null;
}

export function ProfileForm({
  profile,
  email,
  saving,
  error,
  onCancel,
  onSave,
}: ProfileFormProps) {
  const initialMode: "single" | "plan" =
    profile.goal_type === "plan" && profile.north_star?.goal ? "plan" : "single";

  const [goalType, setGoalType] = useState<"single" | "plan">(initialMode);
  const [age, setAge] = useState(profile.age ?? "");
  const [height, setHeight] = useState(profile.height ?? "");
  const [weight, setWeight] = useState(profile.weight ?? "");
  const [location, setLocation] = useState(profile.location ?? "");

  // Single-goal fields
  const [trainingGoal, setTrainingGoal] = useState(profile.training_goal ?? "");
  const [timeline, setTimeline] = useState((profile.timeline ?? "").slice(0, 10));
  const [singleTaper, setSingleTaper] = useState(
    profile.taper_weeks != null ? String(profile.taper_weeks) : "",
  );

  // Plan fields
  const [nsGoal, setNsGoal] = useState(profile.north_star?.goal ?? "");
  const [nsRaceName, setNsRaceName] = useState(
    profile.north_star?.race_name ?? "",
  );
  const [nsStartDate, setNsStartDate] = useState(
    (profile.north_star?.start_date ?? "").slice(0, 10),
  );
  const [nsRaceDate, setNsRaceDate] = useState(
    (profile.north_star?.race_date ?? "").slice(0, 10),
  );
  const [nsTaper, setNsTaper] = useState(
    profile.north_star?.taper_weeks != null
      ? String(profile.north_star.taper_weeks)
      : "3",
  );

  const [subGoals, setSubGoals] = useState<EditableSubGoal[]>(() => {
    if (profile.sub_goals && profile.sub_goals.length > 0) {
      return profile.sub_goals.map((sg) => ({
        goal: sg.goal ?? "",
        race_name: sg.race_name ?? "",
        start_date: (sg.start_date ?? "").slice(0, 10),
        race_date: (sg.race_date ?? "").slice(0, 10),
        taper_weeks: sg.taper_weeks != null ? String(sg.taper_weeks) : "",
        savedResult: sg.result,
      }));
    }
    return [
      {
        goal: "",
        race_name: "",
        start_date: "",
        race_date: "",
        taper_weeks: "1.5",
      },
    ];
  });

  // Training context
  const [personalRecords, setPersonalRecords] = useState(() =>
    toEditablePersonalRecords(profile.personal_records),
  );
  const [injuries, setInjuries] = useState(profile.injuries ?? "");
  const [crossTraining, setCrossTraining] = useState(
    profile.cross_training_strength ?? "",
  );
  const [shoeRotation, setShoeRotation] = useState(() =>
    toEditableShoeRotation(profile.shoe_rotation),
  );

  const [localError, setLocalError] = useState<string | null>(null);

  const fullName =
    `${profile.firstname ?? ""} ${profile.lastname ?? ""}`.trim() || "Runner";

  const parseOptionalNumber = (raw: string): number | null => {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);

    const prError = validatePersonalRecords(personalRecords);
    if (prError) {
      setLocalError(prError);
      return;
    }
    const contextFields = {
      age: age || null,
      height: height || null,
      weight: weight || null,
      location: location || null,
      personal_records: toPersonalRecordsPayload(personalRecords),
      injuries: injuries || null,
      cross_training_strength: crossTraining || null,
      shoe_rotation: toShoeRotationPayload(shoeRotation),
    };

    if (goalType === "single") {
      if (!trainingGoal.trim()) {
        setLocalError("Please enter your target goal (e.g. Sub-1:28 Half Marathon).");
        return;
      }
      if (!timeline.trim()) {
        setLocalError("Please select your target race date.");
        return;
      }
      await onSave({
        ...contextFields,
        goal_type: "single",
        training_goal: trainingGoal.trim(),
        timeline: timeline.trim(),
        taper_weeks: parseOptionalNumber(singleTaper),
        north_star: null,
        sub_goals: [],
      });
      return;
    }

    if (!nsGoal.trim() || !nsRaceDate.trim()) {
      setLocalError("North Star goal and race date are required for a goal plan.");
      return;
    }
    if (subGoals.length === 0) {
      setLocalError("Add at least one stepping-stone sub-goal before your North Star.");
      return;
    }
    for (const sg of subGoals) {
      if (!sg.goal.trim() || !sg.start_date.trim() || !sg.race_date.trim()) {
        setLocalError(
          "Every sub-goal requires a goal label, block start date, and race date.",
        );
        return;
      }
    }

    await onSave({
      ...contextFields,
      goal_type: "plan",
      north_star: {
        goal: nsGoal.trim(),
        race_name: nsRaceName.trim() || null,
        start_date: nsStartDate.trim() || null,
        race_date: nsRaceDate.trim(),
        taper_weeks: parseOptionalNumber(nsTaper),
      },
      sub_goals: subGoals.map((sg) => ({
        goal: sg.goal.trim(),
        race_name: sg.race_name.trim() || null,
        start_date: sg.start_date.trim(),
        race_date: sg.race_date.trim(),
        taper_weeks: parseOptionalNumber(sg.taper_weeks),
      })),
    });
  };

  const displayError = localError || error;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {displayError && (
        <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <span>{displayError}</span>
        </div>
      )}

      {/* Immutable Identity */}
      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Account Identity
          </span>
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Lock className="h-3 w-3" /> Read-only (IAM)
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Runner Name
            </label>
            <input
              type="text"
              value={fullName}
              disabled
              className="w-full rounded-xl border border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-600 cursor-not-allowed"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              IAM Email
            </label>
            <input
              type="text"
              value={profile.email || email}
              disabled
              className="w-full rounded-xl border border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-600 cursor-not-allowed"
            />
          </div>
        </div>
      </div>

      {/* Biometrics & Location */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          Biometrics & Weather Location
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Age
            </label>
            <input
              type="text"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              placeholder="38"
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Height
            </label>
            <input
              type="text"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
              placeholder="183 cm"
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Weight
            </label>
            <input
              type="text"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              placeholder="73.5 kg"
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
            />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Training City / Location
          </label>
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Amsterdam, Netherlands"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
          />
          <p className="mt-1 text-xs text-slate-500">
            Updating your city automatically refreshes weather forecast coordinates on your next check-in.
          </p>
        </div>
      </div>

      {/* Goal Structure */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Goal Structure
          </h3>
          <div className="inline-flex rounded-xl border border-slate-200 bg-slate-100 p-0.5 text-sm">
            <button
              type="button"
              onClick={() => setGoalType("single")}
              className={`rounded-lg px-3 py-1 font-semibold transition cursor-pointer ${
                goalType === "single"
                  ? "bg-white text-slate-900 shadow-2xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Single Goal
            </button>
            <button
              type="button"
              onClick={() => setGoalType("plan")}
              className={`rounded-lg px-3 py-1 font-semibold transition cursor-pointer ${
                goalType === "plan"
                  ? "bg-white text-slate-900 shadow-2xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Goal Plan
            </button>
          </div>
        </div>

        {goalType === "single" ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-4 space-y-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Target Goal
              </label>
              <input
                type="text"
                value={trainingGoal}
                onChange={(e) => setTrainingGoal(e.target.value)}
                placeholder="Sub-1:26 Half Marathon"
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Race Date
                </label>
                <input
                  type="date"
                  value={timeline}
                  onChange={(e) => setTimeline(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Taper Weeks
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0.5"
                  max="6"
                  value={singleTaper}
                  onChange={(e) => setSingleTaper(e.target.value)}
                  placeholder="2"
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Stepping-Stone Sub-Goals */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                  <Flag className="h-3.5 w-3.5 text-orange-500" />
                  Stepping-Stone Sub-Goals
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setSubGoals((prev) => [
                      ...prev,
                      {
                        goal: "",
                        race_name: "",
                        start_date: "",
                        race_date: "",
                        taper_weeks: "1.5",
                      },
                    ])
                  }
                  className="inline-flex items-center gap-1 rounded-lg border border-orange-200 bg-orange-50 px-2.5 py-1 text-sm font-semibold text-orange-700 hover:bg-orange-100 cursor-pointer"
                >
                  <Plus className="h-3.5 w-3.5" /> Add sub-goal
                </button>
              </div>

              {subGoals.map((sg, idx) => (
                <div
                  key={idx}
                  className="rounded-2xl border border-slate-200 bg-slate-50/60 p-3.5 space-y-2.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-600">
                      Block #{idx + 1}
                      {sg.savedResult ? " · Result saved" : ""}
                    </span>
                    {subGoals.length > 1 && (
                      <button
                        type="button"
                        onClick={() =>
                          setSubGoals((prev) => prev.filter((_, i) => i !== idx))
                        }
                        className="inline-flex items-center gap-1 text-xs font-medium text-rose-600 hover:text-rose-800 cursor-pointer"
                      >
                        <Trash2 className="h-3 w-3" /> Remove
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <input
                      type="text"
                      value={sg.goal}
                      onChange={(e) =>
                        setSubGoals((prev) =>
                          prev.map((item, i) =>
                            i === idx ? { ...item, goal: e.target.value } : item,
                          ),
                        )
                      }
                      placeholder="Goal (e.g. Sub-1:26 Half Marathon)"
                      className="rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
                    />
                    <input
                      type="text"
                      value={sg.race_name}
                      onChange={(e) =>
                        setSubGoals((prev) =>
                          prev.map((item, i) =>
                            i === idx
                              ? { ...item, race_name: e.target.value }
                              : item,
                          ),
                        )
                      }
                      placeholder="Event name (optional)"
                      className="rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-2.5">
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-0.5">
                        Block Start
                      </label>
                      <input
                        type="date"
                        value={sg.start_date}
                        onChange={(e) =>
                          setSubGoals((prev) =>
                            prev.map((item, i) =>
                              i === idx
                                ? { ...item, start_date: e.target.value }
                                : item,
                            ),
                          )
                        }
                        className="w-full rounded-xl border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-0.5">
                        Race Date
                      </label>
                      <input
                        type="date"
                        value={sg.race_date}
                        onChange={(e) =>
                          setSubGoals((prev) =>
                            prev.map((item, i) =>
                              i === idx
                                ? { ...item, race_date: e.target.value }
                                : item,
                            ),
                          )
                        }
                        className="w-full rounded-xl border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-0.5">
                        Taper (wks)
                      </label>
                      <input
                        type="number"
                        step="0.5"
                        min="0.5"
                        max="6"
                        value={sg.taper_weeks}
                        onChange={(e) =>
                          setSubGoals((prev) =>
                            prev.map((item, i) =>
                              i === idx
                                ? { ...item, taper_weeks: e.target.value }
                                : item,
                            ),
                          )
                        }
                        className="w-full rounded-xl border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* North Star Goal */}
            <div className="rounded-2xl border border-violet-200 bg-violet-50/50 p-4 space-y-2.5">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-violet-900">
                <Compass className="h-4 w-4 text-violet-600" />
                North Star Destination Race
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <input
                  type="text"
                  value={nsGoal}
                  onChange={(e) => setNsGoal(e.target.value)}
                  placeholder="Sub-2:58 Marathon"
                  className="rounded-xl border border-violet-200 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-violet-500 focus:outline-none"
                />
                <input
                  type="text"
                  value={nsRaceName}
                  onChange={(e) => setNsRaceName(e.target.value)}
                  placeholder="NN Marathon Rotterdam"
                  className="rounded-xl border border-violet-200 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-violet-500 focus:outline-none"
                />
              </div>
              <div className="grid grid-cols-3 gap-2.5">
                <div>
                  <label className="block text-xs font-medium text-violet-700 mb-0.5">
                    Block Start
                  </label>
                  <input
                    type="date"
                    value={nsStartDate}
                    onChange={(e) => setNsStartDate(e.target.value)}
                    className="w-full rounded-xl border border-violet-200 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-violet-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-violet-700 mb-0.5">
                    Race Date
                  </label>
                  <input
                    type="date"
                    value={nsRaceDate}
                    onChange={(e) => setNsRaceDate(e.target.value)}
                    className="w-full rounded-xl border border-violet-200 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-violet-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-violet-700 mb-0.5">
                    Taper (wks)
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="6"
                    value={nsTaper}
                    onChange={(e) => setNsTaper(e.target.value)}
                    className="w-full rounded-xl border border-violet-200 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-violet-500 focus:outline-none"
                  />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Performance & Gear */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          Performance & Gear
        </h3>
        <PersonalRecordsFields
          value={personalRecords}
          onChange={setPersonalRecords}
        />
        <ShoeRotationFields value={shoeRotation} onChange={setShoeRotation} />
      </div>

      {/* Coaching Context */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          Training Context
        </h3>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Injuries & Biomechanical Watchpoints
          </label>
          <textarea
            rows={2}
            value={injuries}
            onChange={(e) => setInjuries(e.target.value)}
            placeholder="Any current niggles, history, or movement notes…"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Strength & Cross-Training
          </label>
          <textarea
            rows={2}
            value={crossTraining}
            onChange={(e) => setCrossTraining(e.target.value)}
            placeholder="2x/wk strength, cycling, swimming…"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/25"
          />
        </div>
      </div>

      <div className="sticky bottom-0 flex items-center justify-end gap-2.5 border-t border-slate-200 bg-white/95 pt-4 pb-1 backdrop-blur-xs">
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-xl bg-sunset bg-sunset-hover px-5 py-2 text-sm font-semibold text-white shadow-sunset transition disabled:opacity-60 cursor-pointer"
        >
          {saving ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Saving…
            </>
          ) : (
            "Save Profile"
          )}
        </button>
      </div>
    </form>
  );
}
