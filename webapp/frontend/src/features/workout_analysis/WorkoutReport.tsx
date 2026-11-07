import type { ReactNode } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bike,
  CalendarDays,
  Droplets,
  Footprints,
  HeartPulse,
  Layers,
  MapPin,
  Moon,
  Mountain,
  Thermometer,
  Wind,
  type LucideIcon,
} from "lucide-react";
import type {
  WorkoutHrZone,
  WorkoutReadiness,
  WorkoutReportData,
  WorkoutTile,
} from "../../shared/types";
import { RichMarkdown, StatusBadge } from "../../shared/RichMarkdown";

interface WorkoutReportProps {
  data: WorkoutReportData;
  markdown: string;
}

/* ---------- Markdown: the banner replaces the coach's Session Overview ---------- */

const OVERVIEW_LINE_RE = /^\s*(?:#{1,6}\s*)?(?:\*\*|__)?[^\w\n]*Session Overview\b.*$/i;
const HEADING_RE = /^\s*#{1,6}\s/;
/** A bold-only line acting as a heading, e.g. "**🎯 Execution**". */
const BOLD_HEADING_RE = /^\s*(?:\*\*|__)[^*_\n]+(?:\*\*|__):?\s*$/;
/** A thematic break: `---`, `***` or `___` (optionally spaced). */
const RULE_RE = /^\s*([-*_])(?:\s*\1){2,}\s*$/;
const TAKEAWAYS_HEADING_RE = /^#{1,6}[^\n\w]*Key Takeaways\b.*$/im;

/** Trims blank lines and thematic breaks from both ends. */
function trimRules(markdown: string): string {
  const lines = markdown.split("\n");
  const isEdge = (l: string) => !l.trim() || RULE_RE.test(l);
  let a = 0;
  let b = lines.length;
  while (a < b && isEdge(lines[a])) a++;
  while (b > a && isEdge(lines[b - 1])) b--;
  return lines.slice(a, b).join("\n");
}

/**
 * Removes the "Session Overview" section (heading or bold pseudo-heading up to the next heading).
 * A title heading that is the only content above the overview is dropped too (the banner shows the
 * title); headings after the overview are never touched.
 */
export function stripSessionOverview(markdown: string): string {
  const lines = markdown.split("\n");
  const start = lines.findIndex((l) => OVERVIEW_LINE_RE.test(l));
  if (start < 0) return trimRules(markdown);
  let end = start + 1;
  while (end < lines.length && !HEADING_RE.test(lines[end]) && !BOLD_HEADING_RE.test(lines[end])) {
    end++;
  }
  const before = lines.slice(0, start);
  const beforeContent = before.filter((l) => l.trim() && !RULE_RE.test(l));
  const keepBefore = beforeContent.length === 1 && HEADING_RE.test(beforeContent[0]) ? [] : before;
  return trimRules([...keepBefore, ...lines.slice(end)].join("\n"));
}

/** Splits at the "Key Takeaways" heading (kept in the second part). */
export function splitTakeaways(markdown: string): { assessment: string; takeaways: string } {
  const m = TAKEAWAYS_HEADING_RE.exec(markdown);
  if (!m) return { assessment: trimRules(markdown), takeaways: "" };
  return {
    assessment: trimRules(markdown.slice(0, m.index)),
    takeaways: trimRules(markdown.slice(m.index)),
  };
}

/* ---------- Formatting ---------- */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Wed 4 Nov 2026" from an ISO date (built by hand so it does not depend on ICU data). */
export function formatWorkoutDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if ([y, m, d].some((n) => Number.isNaN(n))) return iso;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return `${WEEKDAYS[dt.getUTCDay()]} ${d} ${MONTHS[m - 1]} ${y}`;
}

const ZONE_COLORS = ["#60a5fa", "#34d399", "#facc15", "#fb923c", "#f43f5e", "#be123c", "#881337"];

function zoneColor(index: number): string {
  return ZONE_COLORS[Math.min(index, ZONE_COLORS.length - 1)];
}

/* ---------- Header ---------- */

function MetaItem({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <Icon aria-hidden="true" className="h-3.5 w-3.5 text-slate-500" />
      {children}
    </span>
  );
}

function BannerHeader({ data }: { data: WorkoutReportData }) {
  const SportIcon = data.sport_family === "bike" ? Bike : Footprints;
  const date = formatWorkoutDate(data.date);
  const w = data.weather;
  const temp =
    w?.temp_c != null
      ? `${w.temp_c}°C${w.feels_like_c != null && w.feels_like_c !== w.temp_c ? ` (feels ${w.feels_like_c}°C)` : ""}`
      : null;
  return (
    <div
      className="flex flex-wrap items-start justify-between gap-3 border-b border-orange-100 px-5 py-4"
      style={{ backgroundImage: "linear-gradient(135deg, #FFF7ED 0%, #FDF2F8 100%)" }}
    >
      <div className="flex min-w-0 items-center gap-3.5">
        <span className="flex h-11 w-11 flex-none items-center justify-center rounded-xl bg-sunset text-white shadow-xs">
          <SportIcon aria-hidden="true" className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <h3 className="font-display text-lg font-bold leading-tight text-slate-900">{data.title}</h3>
          <div
            data-testid="workout-meta"
            className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-600"
          >
            {date && (
              <MetaItem icon={CalendarDays}>
                {date}
                {data.start_time ? ` · ${data.start_time}` : ""}
              </MetaItem>
            )}
            {data.location && <MetaItem icon={MapPin}>{data.location}</MetaItem>}
            {temp && <MetaItem icon={Thermometer}>{temp}</MetaItem>}
            {w?.humidity != null && <MetaItem icon={Droplets}>{w.humidity}%</MetaItem>}
            {w?.wind_kmh != null && <MetaItem icon={Wind}>{w.wind_kmh} km/h</MetaItem>}
          </div>
        </div>
      </div>
      {data.structured && <StatusBadge tone="slate" icon={Layers} label="Structured" size="sm" />}
    </div>
  );
}

/* ---------- Metrics grid ---------- */

function MetricTile({ tile }: { tile: WorkoutTile }) {
  return (
    <div data-testid="workout-tile" data-key={tile.key} className="min-w-0">
      <div className="text-sm text-slate-500">{tile.label}</div>
      <div className="font-display text-2xl font-bold leading-tight text-slate-900 tabular-nums">
        {tile.value}
        {tile.unit && <span className="ml-1 text-base font-semibold text-slate-700">{tile.unit}</span>}
      </div>
      {tile.sub && <div className="text-xs text-slate-500 tabular-nums">{tile.sub}</div>}
    </div>
  );
}

/* ---------- Elevation sparkline ---------- */

const SPARK_W = 300;
const SPARK_H = 72;
const MIN_ALT_RANGE_M = 10;

export function ElevationSparkline({
  profile,
  gain,
  loss,
}: {
  profile?: Array<[number, number]> | null;
  gain?: number | null;
  loss?: number | null;
}) {
  const label = [gain != null ? `+${gain} m` : null, loss != null ? `-${loss} m` : null]
    .filter(Boolean)
    .join(" / ");
  const pts = profile ?? [];
  let line = "";
  let area = "";
  if (pts.length >= 2) {
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs);
    const xr = Math.max(...xs) - x0 || 1;
    const yMin = Math.min(...ys);
    const yr = Math.max(Math.max(...ys) - yMin, MIN_ALT_RANGE_M);
    const coords = pts.map(([x, y]) => [
      ((x - x0) / xr) * SPARK_W,
      SPARK_H - 4 - ((y - yMin) / yr) * (SPARK_H - 12),
    ]);
    line = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    area = `${line} L${SPARK_W},${SPARK_H} L0,${SPARK_H} Z`;
  }
  if (!line && !label) return null;
  const distance = pts.length ? pts[pts.length - 1][0] : null;
  return (
    <div data-testid="elevation" className="space-y-1">
      <div className="flex items-center justify-between text-xs font-medium text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <Mountain aria-hidden="true" className="h-3.5 w-3.5" />
          Elevation
        </span>
        {label && <span className="font-semibold text-slate-700 tabular-nums">{label}</span>}
      </div>
      {line && (
        <svg
          role="img"
          aria-label={`Elevation profile${label ? ` (${label})` : ""}`}
          viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
          preserveAspectRatio="none"
          className="block h-[72px] w-full"
        >
          <defs>
            <linearGradient id="elev-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fb923c" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#fb923c" stopOpacity="0.03" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#elev-fill)" />
          <path d={line} fill="none" stroke="#f97316" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
      )}
      {line && distance != null && (
        <div className="flex justify-between text-[0.6875rem] text-slate-400 tabular-nums">
          <span>0 km</span>
          <span>{distance.toFixed(1)} km</span>
        </div>
      )}
    </div>
  );
}

/* ---------- HR zones ---------- */

export function HrZoneBar({ zones }: { zones: WorkoutHrZone[] }) {
  return (
    <div data-testid="hr-zones" className="space-y-1.5">
      <div className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500">
        <HeartPulse aria-hidden="true" className="h-3.5 w-3.5" />
        Time in HR zone
      </div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
        {zones.map((z, i) =>
          z.pct > 0 ? (
            <span
              key={z.label}
              data-testid="hr-zone-segment"
              title={`${z.name}: ${z.pct}%`}
              style={{ width: `${z.pct}%`, backgroundColor: zoneColor(i) }}
              className="h-full"
            />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 text-xs text-slate-600 tabular-nums">
        {zones.map((z, i) => (
          <span key={z.label} className="inline-flex items-center gap-1">
            <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: zoneColor(i) }} />
            <span className="font-semibold text-slate-700">{z.label}</span> {Math.round(z.pct)}%
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------- Readiness chips ---------- */

const READINESS_ICONS: Record<string, LucideIcon> = { hrv: HeartPulse, rhr: HeartPulse, sleep: Moon };
const ARROWS: Record<string, LucideIcon> = { up: ArrowUp, down: ArrowDown, flat: ArrowRight };
const ARROW_TONE: Record<string, string> = {
  emerald: "text-emerald-600",
  amber: "text-amber-600",
  rose: "text-rose-600",
  slate: "text-slate-400",
};

function ReadinessChip({ item }: { item: WorkoutReadiness }) {
  const Icon = READINESS_ICONS[item.key] ?? HeartPulse;
  const Arrow = item.direction ? ARROWS[item.direction] : null;
  return (
    <span
      data-testid="readiness-chip"
      data-key={item.key}
      aria-label={`${item.label} ${item.value} ${item.unit}${item.direction ? `, ${item.direction}` : ""}`}
      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-sm text-slate-700"
    >
      <Icon aria-hidden="true" className="h-4 w-4 text-slate-500" />
      <span>{item.label}</span>
      <span className="font-semibold text-slate-900 tabular-nums">
        {item.value} <span className="font-normal">{item.unit}</span>
      </span>
      {Arrow && <Arrow aria-hidden="true" className={`h-3.5 w-3.5 ${ARROW_TONE[item.tone ?? "slate"]}`} />}
    </span>
  );
}

/* ---------- Banner + report ---------- */

export function WorkoutBanner({ data }: { data: WorkoutReportData }) {
  const zones = data.hr_zones?.length ? data.hr_zones : null;
  const elev = data.elevation;
  const hasVisuals = Boolean(zones || elev?.profile?.length || elev?.gain_m != null || elev?.loss_m != null);
  const readiness = data.readiness ?? [];
  const others = data.other_sessions ?? [];
  return (
    <section
      data-testid="workout-banner"
      aria-label="Session overview"
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card"
    >
      <BannerHeader data={data} />
      {(data.tiles.length > 0 || hasVisuals) && (
        <div className={`grid gap-5 px-5 py-4 ${hasVisuals ? "md:grid-cols-[1.15fr_1fr]" : ""}`}>
          {data.tiles.length > 0 && (
            <div className="grid grid-cols-2 content-start gap-x-6 gap-y-4 sm:grid-cols-3">
              {data.tiles.map((t) => (
                <MetricTile key={t.key} tile={t} />
              ))}
            </div>
          )}
          {hasVisuals && (
            <div className="space-y-4 md:border-l md:border-slate-200 md:pl-5">
              {elev && <ElevationSparkline profile={elev.profile} gain={elev.gain_m} loss={elev.loss_m} />}
              {zones && <HrZoneBar zones={zones} />}
            </div>
          )}
        </div>
      )}
      {(readiness.length > 0 || others.length > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-5 py-3">
          <div className="flex flex-wrap gap-2">
            {readiness.map((r) => (
              <ReadinessChip key={r.key} item={r} />
            ))}
          </div>
          {others.length > 0 && (
            <span className="text-xs text-slate-500">
              Also that day: {others.map((s) => s.title).join(", ")}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

export function WorkoutReport({ data, markdown }: WorkoutReportProps) {
  const body = stripSessionOverview(markdown);
  const { assessment, takeaways } = splitTakeaways(body);
  return (
    <div className="space-y-4">
      <WorkoutBanner data={data} />
      {body && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
          {assessment && <RichMarkdown content={assessment} spacing="relaxed" />}
          {takeaways && (
            <div data-testid="workout-takeaways" className={assessment ? "mt-8 border-t border-slate-100 pt-6" : ""}>
              <RichMarkdown content={takeaways} bulletStyle="recommendation" spacing="relaxed" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
