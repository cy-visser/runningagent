import { CalendarPlus, Check, Loader2, RefreshCw, StickyNote } from "lucide-react";
import type { StagedChange, StagedChanges, StagedWorkoutSnapshot } from "../../shared/types";

export type StagedStatus = "pending" | "applying" | "applied" | "replaced";

interface StagedChangesCardProps {
  staged: StagedChanges;
  status: StagedStatus;
  /** Another request is streaming: the button waits. */
  busy?: boolean;
  onApply: (stagedId: string) => void;
}

function dayLabel(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

function num(value: number | null | undefined, unit: string): string {
  return value == null ? "–" : `${Number(value.toFixed(1))} ${unit}`.trim();
}

type ChangeKind = "create" | "update" | "move";

function changeKind(change: StagedChange): ChangeKind {
  if (change.action !== "update") return "create";
  const before = change.replaces?.date;
  return before && before !== change.date.slice(0, 10) ? "move" : "update";
}

const BADGE: Record<ChangeKind, { label: string; className: string }> = {
  create: { label: "Create", className: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  update: { label: "Update", className: "bg-sky-50 text-sky-800 border-sky-200" },
  move: { label: "Move", className: "bg-violet-50 text-violet-800 border-violet-200" },
};

function ActionBadge({ change }: { change: StagedChange }) {
  const { label, className } = BADGE[changeKind(change)];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold border ${className}`}>{label}</span>;
}

interface Metric {
  key: string;
  text: string;
  changed: boolean;
}

/** "10 km · 61 min · TSS 68" (sport first for non-run sessions); `changed` vs the other side when given. */
function metrics(values: StagedWorkoutSnapshot, other?: StagedWorkoutSnapshot | null): Metric[] {
  const out: Metric[] = [];
  const differs = (a?: number | string | null, b?: number | string | null) =>
    other != null && (a ?? null) !== (b ?? null);
  if (values.sport && values.sport.toLowerCase() !== "run") {
    out.push({ key: "sport", text: values.sport, changed: differs(values.sport, other?.sport) });
  }
  if (values.distance_km) {
    out.push({ key: "km", text: num(values.distance_km, "km"), changed: differs(values.distance_km, other?.distance_km) });
  }
  if (values.duration_minutes) {
    out.push({
      key: "min",
      text: num(values.duration_minutes, "min"),
      changed: differs(values.duration_minutes, other?.duration_minutes),
    });
  }
  if (values.tss_planned != null) {
    out.push({ key: "tss", text: `TSS ${num(values.tss_planned, "")}`, changed: differs(values.tss_planned, other?.tss_planned) });
  }
  return out;
}

function WorkoutCell({
  title,
  values,
  compareTo,
  detail,
  dateNote,
}: {
  title: string;
  values: StagedWorkoutSnapshot;
  compareTo?: StagedWorkoutSnapshot | null;
  detail?: string | null;
  dateNote?: string | null;
}) {
  const items = metrics(values, compareTo);
  const titleChanged = compareTo != null && (compareTo.title ?? "") !== title;
  return (
    <div>
      <div className={`text-slate-900 ${titleChanged ? "font-bold" : "font-medium"}`}>
        {title}
        {dateNote && <span className="text-xs font-normal text-slate-500"> ({dateNote})</span>}
      </div>
      {items.length > 0 && (
        <div className="text-xs text-slate-600 tabular-nums">
          {items.map((m, i) => (
            <span key={m.key}>
              {i > 0 && " · "}
              <span className={m.changed ? "font-bold text-slate-900" : undefined}>{m.text}</span>
            </span>
          ))}
        </div>
      )}
      {detail && <div className="text-xs text-slate-500">{detail}</div>}
    </div>
  );
}

function CurrentCell({ change }: { change: StagedChange }) {
  if (change.action !== "update") return <span className="text-slate-400">–</span>;
  const before = change.replaces ?? {};
  const title = before.title || change.replaces_title || "Existing workout";
  const dateNote = changeKind(change) === "move" && before.date ? dayLabel(before.date) : null;
  return (
    <WorkoutCell
      title={title}
      values={before}
      dateNote={dateNote}
      detail={before.structure_summary || before.description_summary}
    />
  );
}

function ApplyButton({ status, busy, onClick }: { status: StagedStatus; busy?: boolean; onClick: () => void }) {
  if (status === "applied") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2 text-sm font-semibold text-emerald-800">
        <Check className="h-4 w-4" /> Applied to TrainingPeaks
      </span>
    );
  }
  if (status === "replaced") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-xl bg-slate-50 border border-slate-200 px-4 py-2 text-sm font-medium text-slate-500">
        <RefreshCw className="h-4 w-4" /> Replaced by newer changes
      </span>
    );
  }
  const applying = status === "applying";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={applying || busy}
      className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-4 py-2 text-sm font-semibold text-white shadow-sunset cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
    >
      {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarPlus className="h-4 w-4" />}
      {applying ? "Updating…" : "Update TrainingPeaks"}
    </button>
  );
}

/** Staged workout / note changes with the button that applies them to TrainingPeaks in code. */
export function StagedChangesCard({ staged, status, busy, onApply }: StagedChangesCardProps) {
  const workouts = staged.changes.filter((c) => c.kind !== "note");
  const notes = staged.changes.filter((c) => c.kind === "note");
  const count = staged.changes.length;

  return (
    <div
      data-testid="staged-changes"
      className="rounded-2xl border border-orange-200/80 bg-white p-5 shadow-card space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-bold text-slate-900">Proposed TrainingPeaks changes</h3>
          <p className="text-sm text-slate-600">
            {count} {count === 1 ? "change" : "changes"}, nothing is written until you apply them.
          </p>
        </div>
        <ApplyButton status={status} busy={busy} onClick={() => onApply(staged.staged_id)} />
      </div>

      {workouts.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
                <th className="py-2 pr-3 font-semibold">Change</th>
                <th className="py-2 pr-3 font-semibold">Date</th>
                <th className="py-2 pr-3 font-semibold">Current workout</th>
                <th className="py-2 font-semibold">Proposed workout</th>
              </tr>
            </thead>
            <tbody>
              {workouts.map((c, i) => (
                <tr key={`${c.date}-${c.title}-${i}`} className="border-b border-slate-100 last:border-0 align-top">
                  <td className="py-2 pr-3"><ActionBadge change={c} /></td>
                  <td className="py-2 pr-3 whitespace-nowrap text-slate-700">{dayLabel(c.date)}</td>
                  <td className="py-2 pr-3 w-1/2"><CurrentCell change={c} /></td>
                  <td className="py-2 w-1/2">
                    <WorkoutCell
                      title={c.title}
                      values={c}
                      compareTo={c.action === "update" ? c.replaces : null}
                      detail={c.structure_summary || c.description_summary}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {notes.length > 0 && (
        <ul className="space-y-1">
          {notes.map((n, i) => (
            <li key={`${n.date}-${n.title}-${i}`} className="flex items-center gap-2 text-sm text-slate-700">
              <StickyNote className="h-4 w-4 text-orange-500" />
              <span className="whitespace-nowrap">{dayLabel(n.date)}</span>
              <span className="font-medium text-slate-900">{n.title}</span>
              <span className="text-xs text-slate-500">(note)</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
