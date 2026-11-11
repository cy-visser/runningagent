import { Trophy } from "lucide-react";
import {
  PR_DISTANCES,
  type EditablePersonalRecords,
} from "./performanceGear";
import type { PersonalRecordKey } from "../../shared/types";

interface PersonalRecordsFieldsProps {
  value: EditablePersonalRecords;
  onChange: (next: EditablePersonalRecords) => void;
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none";

export function PersonalRecordsFields({ value, onChange }: PersonalRecordsFieldsProps) {
  const today = new Date().toLocaleDateString("en-CA");
  const update = (key: PersonalRecordKey, field: "time" | "date", next: string) =>
    onChange({ ...value, [key]: { ...value[key], [field]: next } });

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3.5">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-800">
        <Trophy className="h-3.5 w-3.5 text-orange-500" />
        Personal Records
      </div>
      <div className="grid grid-cols-[4.5rem_5.5rem_1fr] items-center gap-x-2 gap-y-1.5 sm:grid-cols-[7.5rem_7rem_1fr]">
        <span />
        <span className="text-xs font-medium text-slate-500">Time</span>
        <span className="text-xs font-medium text-slate-500">Date</span>
        {PR_DISTANCES.map(({ key, label, shortLabel, placeholder }) => (
          <div key={key} className="contents">
            <label
              htmlFor={`pr-${key}-time`}
              className="text-sm font-medium text-slate-700"
            >
              <span className="sm:hidden">{shortLabel}</span>
              <span className="hidden sm:inline">{label}</span>
            </label>
            <input
              id={`pr-${key}-time`}
              type="text"
              inputMode="numeric"
              aria-label={`${label} PR time`}
              value={value[key].time}
              onChange={(e) => update(key, "time", e.target.value)}
              placeholder={placeholder}
              className={inputClass}
            />
            <input
              type="date"
              max={today}
              aria-label={`${label} PR date`}
              value={value[key].date}
              onChange={(e) => update(key, "date", e.target.value)}
              className={inputClass}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
