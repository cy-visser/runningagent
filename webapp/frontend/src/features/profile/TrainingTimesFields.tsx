import type { TimeOfDay } from "../../shared/types";

export const TIME_OF_DAY_OPTIONS: ReadonlyArray<{ value: TimeOfDay; label: string }> = [
  { value: "morning", label: "Morning" },
  { value: "afternoon", label: "Afternoon" },
  { value: "evening", label: "Evening" },
];

/** "Morning" for a stored value; null when unset or unknown. */
export function timeOfDayLabel(value: string | null | undefined): string | null {
  return TIME_OF_DAY_OPTIONS.find((o) => o.value === value)?.label ?? null;
}

/** Narrows a stored profile value to a TimeOfDay ("" when unset or unknown). */
export function toTimeOfDay(value: string | null | undefined): TimeOfDay | "" {
  return TIME_OF_DAY_OPTIONS.some((o) => o.value === value) ? (value as TimeOfDay) : "";
}

/** "Run: Morning · Strength: Evening" (set preferences only); null when neither is set. */
export function trainingTimesText(profile: {
  run_time_of_day?: string | null;
  strength_time_of_day?: string | null;
}): string | null {
  const parts = [
    ["Run", timeOfDayLabel(profile.run_time_of_day)],
    ["Strength", timeOfDayLabel(profile.strength_time_of_day)],
  ]
    .filter(([, label]) => label)
    .map(([sport, label]) => `${sport}: ${label}`);
  return parts.length ? parts.join(" · ") : null;
}

function TimeOfDayToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: TimeOfDay | "";
  onChange: (value: TimeOfDay) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        className="inline-flex rounded-xl border border-slate-200 bg-slate-100 p-0.5 text-sm"
      >
        {TIME_OF_DAY_OPTIONS.map((option) => {
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(option.value)}
              className={`rounded-lg px-3 py-1 font-semibold transition cursor-pointer ${
                selected ? "bg-white text-slate-900 shadow-2xs" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Required run / strength time-of-day preferences; the plan builder orders double days with them. */
export function TrainingTimesFields({
  run,
  strength,
  onRunChange,
  onStrengthChange,
}: {
  run: TimeOfDay | "";
  strength: TimeOfDay | "";
  onRunChange: (value: TimeOfDay) => void;
  onStrengthChange: (value: TimeOfDay) => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 space-y-3">
      <div>
        <p className="text-sm font-medium text-slate-700">Training Times</p>
        <p className="text-xs text-slate-500">
          When you prefer to train. On days with a run and strength, your plan follows this order.
        </p>
      </div>
      <TimeOfDayToggle label="Run" value={run} onChange={onRunChange} />
      <TimeOfDayToggle label="Strength" value={strength} onChange={onStrengthChange} />
    </div>
  );
}
