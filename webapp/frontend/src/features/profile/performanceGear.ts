import type {
  PersonalRecordKey,
  PersonalRecords,
  ShoeRotation,
  ShoeSlotKey,
} from "../../shared/types";

export const PR_DISTANCES: ReadonlyArray<{
  key: PersonalRecordKey;
  label: string;
  shortLabel: string;
  placeholder: string;
}> = [
  { key: "5k", label: "5K", shortLabel: "5K", placeholder: "19:45" },
  { key: "10k", label: "10K", shortLabel: "10K", placeholder: "39:12" },
  { key: "10_mile", label: "10 Mile", shortLabel: "10 Mile", placeholder: "1:05:30" },
  { key: "half_marathon", label: "Half Marathon", shortLabel: "HM", placeholder: "1:27:48" },
  { key: "marathon", label: "Marathon", shortLabel: "Marathon", placeholder: "3:04:19" },
];

export const SHOE_SLOTS: ReadonlyArray<{
  key: ShoeSlotKey;
  label: string;
  placeholder: string;
}> = [
  { key: "easy", label: "Easy", placeholder: "Superblast 2" },
  { key: "tempo", label: "Tempo/Threshold", placeholder: "Magic Speed 4" },
  { key: "interval", label: "Interval", placeholder: "Takumi Sen 10" },
  { key: "long_run", label: "Long run", placeholder: "Superblast 2" },
  { key: "race", label: "Race", placeholder: "Metaspeed Sky Paris" },
];

export type EditablePersonalRecords = Record<
  PersonalRecordKey,
  { time: string; date: string }
>;
export type EditableShoeRotation = Record<ShoeSlotKey, string>;

const RACE_TIME_RE = /^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})$/;

/** Mirrors the backend parser: MM:SS or H:MM:SS, seconds < 60, minutes < 60 when hours are given. */
export function isValidRaceTime(raw: string): boolean {
  const match = RACE_TIME_RE.exec(raw.trim());
  if (!match) return false;
  const hours = Number(match[1] ?? 0);
  const minutes = Number(match[2]);
  const seconds = Number(match[3]);
  if (seconds >= 60 || (match[1] !== undefined && minutes >= 60)) return false;
  return hours * 3600 + minutes * 60 + seconds > 0;
}

export function toEditablePersonalRecords(
  records: PersonalRecords | null | undefined,
): EditablePersonalRecords {
  return Object.fromEntries(
    PR_DISTANCES.map(({ key }) => [
      key,
      {
        time: records?.[key]?.time ?? "",
        date: (records?.[key]?.date ?? "").slice(0, 10),
      },
    ]),
  ) as EditablePersonalRecords;
}

export function toEditableShoeRotation(
  shoes: ShoeRotation | null | undefined,
): EditableShoeRotation {
  return Object.fromEntries(
    SHOE_SLOTS.map(({ key }) => [key, shoes?.[key] ?? ""]),
  ) as EditableShoeRotation;
}

/** Returns a user-facing error for the first invalid PR row, or null. */
export function validatePersonalRecords(
  records: EditablePersonalRecords,
): string | null {
  for (const { key, label } of PR_DISTANCES) {
    const { time, date } = records[key];
    if (!time.trim()) {
      if (date.trim()) return `${label} PR: enter a time for the selected date.`;
      continue;
    }
    if (!isValidRaceTime(time)) {
      return `${label} PR: use MM:SS or H:MM:SS (e.g. 1:27:48).`;
    }
  }
  return null;
}

export function toPersonalRecordsPayload(
  records: EditablePersonalRecords,
): PersonalRecords | null {
  const payload: PersonalRecords = {};
  let any = false;
  for (const { key } of PR_DISTANCES) {
    const time = records[key].time.trim();
    const date = records[key].date.trim();
    payload[key] = time ? { time, date: date || null } : null;
    any = any || Boolean(time);
  }
  return any ? payload : null;
}

export function toShoeRotationPayload(
  shoes: EditableShoeRotation,
): ShoeRotation | null {
  const payload: ShoeRotation = {};
  let any = false;
  for (const { key } of SHOE_SLOTS) {
    const value = shoes[key].trim();
    payload[key] = value || null;
    any = any || Boolean(value);
  }
  return any ? payload : null;
}
