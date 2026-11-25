import { useState } from "react";
import { formatShortDate } from "../../shared/format";
import type { YearReviewHeatmap, YearReviewHeatmapDay } from "../../shared/types";

interface ActivityHeatmapProps {
  year?: number;
  isComplete?: boolean;
  heatmap: YearReviewHeatmap;
}

const LEVEL_CLASSES: Record<number, string> = {
  [-2]: "border border-dashed border-slate-200 bg-transparent",
  [-1]: "bg-transparent",
  0: "bg-slate-100",
  1: "bg-orange-200",
  2: "bg-orange-400",
  3: "bg-orange-500",
  4: "bg-pink-500",
};

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthHeaders(weeks: YearReviewHeatmap["weeks"]): Array<{ col: number; label: string }> {
  const out: Array<{ col: number; label: string }> = [];
  let prevMonth = -1;
  weeks.forEach((wk, idx) => {
    const month = Number(wk.week.slice(5, 7)) - 1;
    if (!Number.isNaN(month) && month !== prevMonth) {
      if (out.length === 0 || idx - out[out.length - 1].col >= 3) {
        out.push({ col: idx, label: MONTH_NAMES[month] ?? "" });
      }
      prevMonth = month;
    }
  });
  return out;
}

export function ActivityHeatmap({ year, isComplete = true, heatmap }: ActivityHeatmapProps) {
  const [hovered, setHovered] = useState<YearReviewHeatmapDay | null>(null);
  const weeks = heatmap.weeks ?? [];
  if (weeks.length === 0) return null;

  const headers = monthHeaders(weeks);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 shadow-card flex flex-col justify-between gap-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-display text-sm font-bold text-slate-900">
            {year ? `${year} ` : ""}Activity Heatmap (Jan 1 – Dec 31)
          </h3>
          <p className="text-xs text-slate-500">
            Daily running volume across the calendar year · races highlighted{!isComplete ? " · remaining days dashed" : ""}
          </p>
        </div>
        {hovered && hovered.level >= 0 && (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[0.6875rem] font-medium text-slate-700 tabular-nums">
            {formatShortDate(hovered.date)} ·{" "}
            {hovered.km > 0 ? `${hovered.km.toFixed(1)} km` : "Rest / cross"}
            {hovered.race_name ? ` · ${hovered.race_name}` : ""}
          </span>
        )}
      </div>

      <div className="overflow-x-auto pb-1">
        <div className="min-w-[30rem]">
          {/* Month markers */}
          <div className="relative mb-1.5 ml-5 h-3.5 text-[0.625rem] font-medium text-slate-500">
            {headers.map((h) => (
              <span
                key={`${h.col}-${h.label}`}
                style={{ left: `${(h.col / weeks.length) * 100}%` }}
                className="absolute top-0"
              >
                {h.label}
              </span>
            ))}
          </div>

          <div className="flex items-stretch gap-1.5">
            <div className="flex w-3.5 flex-col justify-between py-0.5 text-[0.5625rem] font-medium text-slate-400">
              <span>M</span>
              <span>W</span>
              <span>F</span>
              <span>S</span>
            </div>

            <div
              className="grid flex-1 gap-[2px]"
              style={{
                gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))`,
              }}
              onMouseLeave={() => setHovered(null)}
            >
              {weeks.map((wk) => (
                <div key={wk.week} className="grid grid-rows-7 gap-[2px]">
                  {wk.days.map((day) => {
                    const cls = day.is_race
                      ? "bg-violet-600 ring-1 ring-amber-400"
                      : (LEVEL_CLASSES[day.level] ?? "bg-slate-100");
                    const label =
                      day.level < 0
                        ? ""
                        : `${formatShortDate(day.date)}: ${day.km > 0 ? `${day.km.toFixed(1)} km` : "Rest"}${
                            day.race_name ? ` (${day.race_name})` : ""
                          }`;
                    return (
                      <div
                        key={day.date}
                        title={label}
                        aria-label={label || undefined}
                        onMouseEnter={() => {
                          if (day.level >= 0) setHovered(day);
                        }}
                        className={`h-2.5 w-full rounded-[2px] transition-opacity ${cls}`}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[0.6875rem] text-slate-500 tabular-nums">
        <span>
          {heatmap.run_days} run days · {heatmap.longest_streak_weeks}-week longest streak
        </span>
        <div className="flex items-center gap-1.5">
          <span>Rest</span>
          <span className="h-2.5 w-2.5 rounded-[2px] bg-slate-100" />
          <span className="h-2.5 w-2.5 rounded-[2px] bg-orange-200" />
          <span className="h-2.5 w-2.5 rounded-[2px] bg-orange-400" />
          <span className="h-2.5 w-2.5 rounded-[2px] bg-orange-500" />
          <span className="h-2.5 w-2.5 rounded-[2px] bg-pink-500" />
          <span>Long</span>
          <span className="ml-2 inline-flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-violet-600 ring-1 ring-amber-400" />
            Race
          </span>
          {!isComplete && (
            <span className="ml-2 inline-flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-[2px] border border-dashed border-slate-300 bg-transparent" />
              Remaining
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
