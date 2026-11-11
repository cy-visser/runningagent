import { Footprints } from "lucide-react";
import { SHOE_SLOTS, type EditableShoeRotation } from "./performanceGear";

interface ShoeRotationFieldsProps {
  value: EditableShoeRotation;
  onChange: (next: EditableShoeRotation) => void;
}

export function ShoeRotationFields({ value, onChange }: ShoeRotationFieldsProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3.5">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-800">
        <Footprints className="h-3.5 w-3.5 text-orange-500" />
        Shoe Rotation
      </div>
      <div className="grid grid-cols-1 gap-y-1.5">
        {SHOE_SLOTS.map(({ key, label, placeholder }) => (
          <div key={key} className="grid grid-cols-[7.5rem_1fr] items-center gap-2">
            <label
              htmlFor={`shoe-${key}`}
              className="text-sm font-medium text-slate-700"
            >
              {label}
            </label>
            <input
              id={`shoe-${key}`}
              type="text"
              maxLength={120}
              value={value[key]}
              onChange={(e) => onChange({ ...value, [key]: e.target.value })}
              placeholder={placeholder}
              className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-orange-500 focus:outline-none"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
