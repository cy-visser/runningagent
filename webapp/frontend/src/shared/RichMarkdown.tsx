import React, { createContext, useContext, useId } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Flag,
  Info,
  Lightbulb,
  Minus,
  Star,
  TrendingDown,
  TrendingUp,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  DEFAULT_TONE_ICON,
  extractLeadingStatus,
  matchLeadingStatusEmoji,
  normalizeCoachMarkdown,
  parseAsciiProgressBar,
  splitReportPlaceholders,
  type StatusEmojiInfo,
  type StatusIconKey,
  type StatusPillTone,
} from "./format";

/** hast node shape used by rehypeBrOnly (avoids a direct @types/hast dependency). */
interface HastNode {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

const BR_RE = /^<br\s*\/?>$/i;

/**
 * Rehype plugin: turns raw `<br>` / `<br/>` (models put them in table cells) into real line breaks.
 * Every other raw HTML node is left alone, so react-markdown still renders it as escaped text.
 */
function rehypeBrOnly() {
  const walk = (node: HastNode) => {
    node.children?.forEach((child, i) => {
      if (child.type === "raw" && BR_RE.test((child.value ?? "").trim())) {
        node.children![i] = { type: "element", tagName: "br", properties: {}, children: [] };
      } else {
        walk(child);
      }
    });
  };
  return (tree: HastNode) => walk(tree);
}

/** "recommendation" swaps list bullets for indigo icon squares (Flag / Star / Lightbulb). */
export type BulletStyle = "default" | "recommendation";

/** "relaxed" gives sections more air (used by the workout analysis). */
export type MarkdownSpacing = "normal" | "relaxed";

interface RichMarkdownProps {
  content: string;
  bulletStyle?: BulletStyle;
  spacing?: MarkdownSpacing;
}

/** Heading margins per spacing; relaxed sections also get a hairline above (not on the first). */
const SECTION_CLASS: Record<MarkdownSpacing, { section: string; sub: string; root: string }> = {
  normal: { section: "mt-4 first:mt-0", sub: "mt-3.5 first:mt-0", root: "space-y-3" },
  relaxed: {
    section: "mt-8 border-t border-slate-100 pt-6 first:mt-0 first:border-t-0 first:pt-0",
    sub: "mt-5 first:mt-0",
    root: "space-y-4",
  },
};

/* ---------- Status badge (style B: outline chip) ---------- */

const STATUS_ICONS: Record<StatusIconKey, LucideIcon> = {
  check: CheckCircle2,
  alert: AlertTriangle,
  x: XCircle,
  info: Info,
  up: TrendingUp,
  down: TrendingDown,
  flat: Minus,
  dashed: CircleDashed,
};

const BADGE_BORDER: Record<StatusPillTone, string> = {
  emerald: "border-emerald-300",
  amber: "border-amber-300",
  rose: "border-rose-300",
  slate: "border-slate-300",
};

const BADGE_ICON: Record<StatusPillTone, string> = {
  emerald: "text-emerald-600",
  amber: "text-amber-600",
  rose: "text-rose-600",
  slate: "text-slate-500",
};

/** Solid fill for the small status chip so it stands out on white cards. */
const CHIP_FILL: Record<StatusPillTone, string> = {
  emerald: "bg-emerald-600 border-emerald-700",
  amber: "bg-amber-500 border-amber-600",
  rose: "bg-rose-600 border-rose-700",
  slate: "bg-slate-500 border-slate-600",
};

const BADGE_SIZE = {
  sm: { box: "gap-1 py-px pl-1.5 pr-2 text-[0.6875rem]", icon: "h-3 w-3" },
  md: { box: "gap-1.5 py-0.5 pl-[7px] pr-[9px] text-sm", icon: "h-3.5 w-3.5" },
  lg: { box: "gap-2 py-1.5 pl-[11px] pr-3.5 text-[0.9375rem]", icon: "h-[17px] w-[17px]" },
} as const;

const CHIP_LABEL: Partial<Record<StatusIconKey, string>> = {
  check: "OK",
  alert: "Warning",
  x: "Problem",
  info: "Info",
};

/** Direction of a number: the arrow on a badge shows where the value moved. */
export type BadgeDirection = "up" | "down" | "flat";

/** Maps a payload arrow (↑ ↓ →) to a badge direction; undefined when unknown. */
export function directionFromArrow(arrow: string | null | undefined): BadgeDirection | undefined {
  if (!arrow) return undefined;
  if (arrow.includes("↑")) return "up";
  if (arrow.includes("↓")) return "down";
  if (arrow.includes("→")) return "flat";
  return undefined;
}

function resolveIcon(
  tone: StatusPillTone,
  icon?: LucideIcon | StatusIconKey,
  direction?: BadgeDirection,
): LucideIcon {
  if (typeof icon === "string") return STATUS_ICONS[icon];
  if (icon) return icon;
  if (direction) return STATUS_ICONS[direction];
  return STATUS_ICONS[DEFAULT_TONE_ICON[tone]];
}

export interface StatusBadgeProps {
  tone: StatusPillTone;
  label: string;
  /** Lucide icon or icon key; defaults to the tone's icon (check / alert / x / info). */
  icon?: LucideIcon | StatusIconKey;
  /**
   * Direction-aware badge: the arrow shows the number's direction, the tone shows good/bad
   * (e.g. falling RHR that is good = direction "down" + tone "emerald"). Ignored when `icon` is set.
   */
  direction?: BadgeDirection;
  size?: keyof typeof BADGE_SIZE;
  className?: string;
}

/** Outline chip: white fill, 1px coloured border, coloured icon, slate text. */
export function StatusBadge({
  tone,
  label,
  icon,
  direction,
  size = "md",
  className = "",
}: StatusBadgeProps) {
  const Icon = resolveIcon(tone, icon, direction);
  const s = BADGE_SIZE[size];
  return (
    <span
      data-testid="status-badge"
      data-tone={tone}
      className={`inline-flex items-center rounded-md border bg-white font-semibold text-slate-700 whitespace-nowrap ${s.box} ${BADGE_BORDER[tone]} ${className}`}
    >
      <Icon aria-hidden="true" className={`flex-none ${s.icon} ${BADGE_ICON[tone]}`} />
      <span>{label}</span>
    </span>
  );
}

/** Backwards-compatible alias: same props as before, now rendered as a StatusBadge. */
export function StatusPill(props: StatusBadgeProps) {
  return <StatusBadge {...props} />;
}

/** Small square icon chip that replaces a leading ✅ ⚠️ ❌ 🟢 🟡 🔴 ⚪ in coach text. */
export function StatusChip({ tone, icon }: { tone: StatusPillTone; icon: StatusIconKey }) {
  const Icon = STATUS_ICONS[icon];
  return (
    <span
      data-testid="status-chip"
      data-tone={tone}
      role="img"
      aria-label={CHIP_LABEL[icon] ?? icon}
      className={`mr-1.5 inline-flex h-5 w-5 flex-none items-center justify-center rounded-md border shadow-xs align-[-0.3em] ${CHIP_FILL[tone]}`}
    >
      <Icon aria-hidden="true" strokeWidth={2.5} className="h-[13px] w-[13px] text-white" />
    </span>
  );
}

/* ---------- Recommendation icons ---------- */

export type RecommendationKind = "subgoal" | "northstar" | "tip";

const RECOMMENDATION_ICONS: Record<RecommendationKind, LucideIcon> = {
  subgoal: Flag,
  northstar: Star,
  tip: Lightbulb,
};

const RECOMMENDATION_LABEL: Record<RecommendationKind, string> = {
  subgoal: "Sub goal",
  northstar: "North star",
  tip: "Recommendation",
};

/** Solid fill per kind; deliberately avoids status tones (emerald/amber/rose/slate). */
const RECOMMENDATION_FILL: Record<RecommendationKind, string> = {
  subgoal: "bg-indigo-600 border-indigo-700",
  northstar: "bg-indigo-600 border-indigo-700",
  tip: "bg-indigo-600 border-indigo-700",
};

/** Classifies a recommendation by its leading label ("Sub goal" / "North star"); null otherwise. */
export function recommendationKindFromText(text: string): RecommendationKind | null {
  const t = text.replace(/^[\s*_]+/, "");
  if (/^sub[\s-]?goal/i.test(t)) return "subgoal";
  if (/^north[\s-]?star/i.test(t)) return "northstar";
  return null;
}

/** Indigo square with a white icon that replaces a recommendation bullet. */
export function RecommendationIcon({ kind }: { kind: RecommendationKind }) {
  const Icon = RECOMMENDATION_ICONS[kind];
  return (
    <span
      data-testid="recommendation-icon"
      data-icon={kind}
      role="img"
      aria-label={RECOMMENDATION_LABEL[kind]}
      className={`mt-px inline-flex h-6 w-6 flex-none items-center justify-center rounded-lg border text-white shadow-xs ${RECOMMENDATION_FILL[kind]}`}
    >
      <Icon aria-hidden="true" strokeWidth={2.25} className="h-3.5 w-3.5" />
    </span>
  );
}

interface BulletContextValue {
  style: BulletStyle;
  /** Kind inherited from a parent "Sub goal" / "North star" item. */
  inherited: RecommendationKind | null;
  /** Nesting depth of the list currently being rendered (0 = top level). */
  depth: number;
  /** True inside an ordered list (items get a number badge instead of a sparkle). */
  ordered: boolean;
}

const BulletContext = createContext<BulletContextValue>({
  style: "default",
  inherited: null,
  depth: 0,
  ordered: false,
});

/* ---------- Default bullet markers (gradient sparkle / number badge) ---------- */

const SPARKLE_PATH =
  "M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z";

/** Sunset-gradient sparkle replacing a plain bullet; nested levels use a smaller outlined sparkle. */
export function BulletIcon({ depth = 0 }: { depth?: number }) {
  const gradientId = `sparkle-${useId().replace(/:/g, "")}`;
  if (depth > 0) {
    return (
      <span data-testid="bullet-icon" data-depth={depth} aria-hidden="true" className="mt-[6px] flex-none">
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="#fb923c" strokeWidth={2.2} strokeLinejoin="round">
          <path d={SPARKLE_PATH} />
        </svg>
      </span>
    );
  }
  return (
    <span data-testid="bullet-icon" data-depth={0} aria-hidden="true" className="mt-[4px] flex-none">
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" strokeWidth={1} strokeLinejoin="round">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f97316" />
            <stop offset="100%" stopColor="#ec4899" />
          </linearGradient>
        </defs>
        <path d={SPARKLE_PATH} fill={`url(#${gradientId})`} stroke={`url(#${gradientId})`} />
      </svg>
    </span>
  );
}

/** Soft orange circle with the item number, replacing "1." in ordered lists. */
export function NumberBadge({ n }: { n: number }) {
  return (
    <span
      data-testid="number-badge"
      aria-hidden="true"
      className="mt-[3px] inline-flex h-5 min-w-5 flex-none items-center justify-center rounded-full border border-orange-200 bg-orange-50 px-1 text-[0.6875rem] font-bold text-orange-700 tabular-nums"
    >
      {n}
    </span>
  );
}

/* ---------- Markdown helpers ---------- */

function flattenChildrenText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(flattenChildrenText).join("");
  }
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    return flattenChildrenText(props.children);
  }
  return "";
}

type ElementWithChildren = React.ReactElement<{ children?: React.ReactNode }>;

interface StrippedStatus {
  info: StatusEmojiInfo;
  rest: React.ReactNode[];
}

function MdStrong({ children }: { children?: React.ReactNode }) {
  return <strong className="font-semibold text-slate-900">{children}</strong>;
}

function MdEm({ children }: { children?: React.ReactNode }) {
  return <em>{children}</em>;
}

/** Inline elements we may descend into to find a leading emoji (e.g. `**🟢 Title:**`). */
const INLINE_TYPES: unknown[] = [MdStrong, MdEm, "strong", "em", "b", "i", "span"];

/**
 * Removes a leading status emoji from React children, keeping all other children (and nested
 * inline elements such as <strong>) intact. Returns null when the content does not start with one.
 */
function stripLeadingStatusEmoji(children: React.ReactNode): StrippedStatus | null {
  const arr = React.Children.toArray(children);
  let i = 0;
  while (i < arr.length && typeof arr[i] === "string" && !(arr[i] as string).trim()) i++;
  if (i >= arr.length) return null;
  const first = arr[i];
  if (typeof first === "string" || typeof first === "number") {
    const m = matchLeadingStatusEmoji(String(first));
    if (!m) return null;
    const rest = [m.rest, ...arr.slice(i + 1)].filter((c) => c !== "");
    return { info: m, rest };
  }
  if (React.isValidElement(first) && INLINE_TYPES.includes(first.type)) {
    const el = first as ElementWithChildren;
    const inner = stripLeadingStatusEmoji(el.props.children);
    if (!inner) return null;
    const cloned = React.cloneElement(el, undefined, ...inner.rest);
    return { info: inner.info, rest: [cloned, ...arr.slice(i + 1)] };
  }
  return null;
}

const MAX_HERO_LABEL = 28;
const HERO_LEAD_RE = /^([A-Za-z][^.:!?—–\n]{0,26}?)\s*(?:[.:!]|\s[—–])(?:\s+|$)/;

function wordCount(s: string): number {
  return s.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Splits a short verdict label ("On Track", "**At Risk**") off the start of a paragraph.
 * Returns null when the paragraph does not open with a short verdict phrase.
 */
function splitHeroVerdict(rest: React.ReactNode[]): { label: string; rest: React.ReactNode[] } | null {
  const [first, ...others] = rest;
  if (typeof first === "string") {
    const trimmed = first.replace(/^\s+/, "");
    const m = HERO_LEAD_RE.exec(trimmed);
    if (!m || wordCount(m[1]) > 4) return null;
    const remainder = trimmed.slice(m[0].length);
    return { label: m[1].trim(), rest: [remainder, ...others].filter((c) => c !== "") };
  }
  if (React.isValidElement(first) && INLINE_TYPES.includes(first.type)) {
    const label = flattenChildrenText(first).trim();
    const next = others[0];
    if (!label || label.length > MAX_HERO_LABEL || wordCount(label) > 4) return null;
    if (typeof next !== "string" || !/^\s*[.:!—–]/.test(next)) return null;
    const remainder = next.replace(/^\s*[.:!—–]\s*/, "");
    return { label: label.replace(/[.:!]$/, ""), rest: [remainder, ...others.slice(1)].filter((c) => c !== "") };
  }
  return null;
}

function withLeadingChip(children: React.ReactNode): React.ReactNode {
  const stripped = stripLeadingStatusEmoji(children);
  if (!stripped) return children;
  return (
    <>
      <StatusChip tone={stripped.info.tone} icon={stripped.info.icon} />
      {stripped.rest}
    </>
  );
}

const P_CLASS = "leading-relaxed text-slate-700 my-2 first:mt-0 last:mb-0";

function MdParagraph({ children }: { children?: React.ReactNode }) {
  const stripped = stripLeadingStatusEmoji(children);
  if (!stripped) {
    return <p className={P_CLASS}>{children}</p>;
  }
  const { info } = stripped;
  if (info.verdict) {
    const restText = flattenChildrenText(stripped.rest).trim();
    if (restText && restText.length <= MAX_HERO_LABEL && wordCount(restText) <= 4) {
      // Paragraph that is only a verdict, e.g. "🟢 On Track".
      return (
        <div className="my-2 first:mt-0 last:mb-0">
          <StatusBadge tone={info.tone} icon={info.icon} label={restText} size="lg" />
        </div>
      );
    }
    const hero = splitHeroVerdict(stripped.rest);
    if (hero) {
      // "🟢 On Track. CTL has climbed …" -> hero badge + the rest of the paragraph.
      return (
        <div className="my-2 space-y-2 first:mt-0 last:mb-0">
          <StatusBadge tone={info.tone} icon={info.icon} label={hero.label} size="lg" />
          {hero.rest.length > 0 && <p className="leading-relaxed text-slate-700">{hero.rest}</p>}
        </div>
      );
    }
  }
  return (
    <p className={P_CLASS}>
      <StatusChip tone={info.tone} icon={info.icon} />
      {stripped.rest}
    </p>
  );
}

function MdListItem({
  children,
  className,
  ordinal,
}: {
  children?: React.ReactNode;
  className?: string;
  /** Item number, injected by MdList for ordered lists. */
  ordinal?: number;
}) {
  const bullet = useContext(BulletContext);
  if (bullet.style === "recommendation") {
    return <RecommendationListItem inherited={bullet.inherited}>{children}</RecommendationListItem>;
  }
  // GFM task list item ("- [ ] …"): keep the checkbox as its marker.
  if (className?.includes("task-list-item")) {
    return <li className={`leading-relaxed ${className}`}>{children}</li>;
  }
  const arr = React.Children.toArray(children);
  const firstEl = arr.find((c) => !(typeof c === "string" && !c.trim()));
  const isLoose = React.isValidElement(firstEl) && firstEl.type === MdParagraph;
  // Loose list items wrap their text in a paragraph; MdParagraph draws the status chip itself.
  const looseStatus =
    isLoose && stripLeadingStatusEmoji((firstEl as ElementWithChildren).props.children) !== null;
  const stripped = isLoose ? null : stripLeadingStatusEmoji(children);

  let marker: React.ReactNode = null;
  if (stripped) {
    marker = <StatusChip tone={stripped.info.tone} icon={stripped.info.icon} />;
  } else if (!looseStatus) {
    marker = bullet.ordered && ordinal !== undefined
      ? <NumberBadge n={ordinal} />
      : <BulletIcon depth={bullet.depth} />;
  }
  return (
    <li className="flex items-start gap-2.5 leading-relaxed [&>[data-testid=status-chip]]:mr-0 [&>[data-testid=status-chip]]:mt-[3px]">
      {marker}
      <div className="min-w-0 flex-1 [&>p]:my-0 [&>p+p]:mt-2">
        <BulletContext.Provider value={{ ...bullet, depth: bullet.depth + 1 }}>
          {stripped ? stripped.rest : children}
        </BulletContext.Provider>
      </div>
    </li>
  );
}

/** Text of a list item without its nested lists, used to classify the item. */
function ownItemText(children: React.ReactNode): string {
  return React.Children.toArray(children)
    .filter(
      (c) => !(React.isValidElement(c) && (c.type === "ul" || c.type === "ol" || c.type === MdUl || c.type === MdOl)),
    )
    .map(flattenChildrenText)
    .join("")
    .trim();
}

function RecommendationListItem({
  children,
  inherited,
}: {
  children?: React.ReactNode;
  inherited: RecommendationKind | null;
}) {
  const bullet = useContext(BulletContext);
  // A leading status emoji keeps its status chip instead of a recommendation icon.
  const stripped = stripLeadingStatusEmoji(children);
  const kind = recommendationKindFromText(ownItemText(children)) ?? inherited ?? "tip";
  return (
    <li className="flex items-start gap-2.5 leading-relaxed">
      {stripped ? (
        <StatusChip tone={stripped.info.tone} icon={stripped.info.icon} />
      ) : (
        <RecommendationIcon kind={kind} />
      )}
      <div className="min-w-0 flex-1 [&>p]:my-0">
        <BulletContext.Provider
          value={{ ...bullet, style: "recommendation", inherited: kind === "tip" ? inherited : kind }}
        >
          {stripped ? stripped.rest : children}
        </BulletContext.Provider>
      </div>
    </li>
  );
}

function MdList({ children, ordered, start }: { children?: React.ReactNode; ordered?: boolean; start?: number }) {
  const bullet = useContext(BulletContext);
  if (bullet.style === "recommendation") {
    return <ul className="my-2 list-none space-y-2 pl-0 text-slate-700">{children}</ul>;
  }
  const Tag = ordered ? "ol" : "ul";
  // Number the items ourselves (honouring `start`) so each one can draw its badge.
  let n = typeof start === "number" ? start : 1;
  const items = ordered
    ? React.Children.map(children, (c) =>
        React.isValidElement(c) && c.type === MdListItem
          ? React.cloneElement(c as React.ReactElement<{ ordinal?: number }>, { ordinal: n++ })
          : c,
      )
    : children;
  return (
    <BulletContext.Provider value={{ ...bullet, ordered: Boolean(ordered) }}>
      <Tag className={`my-2 list-none space-y-1.5 pl-0 text-slate-700 ${bullet.depth > 0 ? "mt-1.5" : ""}`}>
        {items}
      </Tag>
    </BulletContext.Provider>
  );
}

function MdUl({ children }: { children?: React.ReactNode }) {
  return <MdList>{children}</MdList>;
}

function MdOl({ children, start }: { children?: React.ReactNode; start?: number }) {
  return <MdList ordered start={start}>{children}</MdList>;
}

export function SunsetProgressBar({ percent }: { percent: number }) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <span
      className="inline-flex items-center gap-2 align-middle"
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span className="inline-block h-2 w-24 overflow-hidden rounded-full bg-slate-100 border border-slate-200/80">
        <span
          className="block h-full rounded-full bg-sunset transition-all duration-300"
          style={{ width: `${clamped}%` }}
        />
      </span>
    </span>
  );
}

export function RichMarkdown({ content, bulletStyle = "default", spacing = "normal" }: RichMarkdownProps) {
  const segments = splitReportPlaceholders(normalizeCoachMarkdown(content));
  const sp = SECTION_CLASS[spacing];

  return (
    <BulletContext.Provider value={{ style: bulletStyle, inherited: null, depth: 0, ordered: false }}>
    <div data-spacing={spacing} className={`${sp.root} text-base leading-relaxed text-slate-700`}>
      {segments.map((seg, idx) => {
        if (seg.type === "placeholder") {
          return (
            <div
              key={`ph-${idx}`}
              className="rounded-2xl border border-orange-200/70 p-4 animate-shimmer"
            >
              <div className="h-3 w-44 rounded-full bg-orange-200/60 mb-2.5" />
              <div className="h-2.5 w-full rounded-full bg-slate-200/70 mb-2" />
              <div className="h-2.5 w-4/5 rounded-full bg-slate-200/70" />
            </div>
          );
        }

        return (
          <ReactMarkdown
            key={`md-${idx}`}
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeBrOnly]}
            components={{
              h1: ({ children }) => (
                <h1 className="font-display text-lg font-bold text-slate-900 mt-4 mb-2 first:mt-0">
                  {withLeadingChip(children)}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className={`font-display text-lg font-bold text-slate-900 mb-2 ${sp.section}`}>
                  {withLeadingChip(children)}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className={`font-display text-base font-bold text-slate-900 mb-1.5 ${sp.section}`}>
                  {withLeadingChip(children)}
                </h3>
              ),
              h4: ({ children }) => (
                <h4 className={`font-display text-[0.9375rem] font-semibold text-slate-800 mb-1 ${sp.sub}`}>
                  {withLeadingChip(children)}
                </h4>
              ),
              h5: ({ children }) => (
                <h5 className="font-display text-sm font-semibold text-slate-800 mt-3 mb-1 first:mt-0">
                  {withLeadingChip(children)}
                </h5>
              ),
              h6: ({ children }) => (
                <h6 className="font-display text-sm font-semibold text-slate-600 mt-3 mb-1 first:mt-0">
                  {withLeadingChip(children)}
                </h6>
              ),
              hr: () => <hr className="my-4 border-slate-200" />,
              p: MdParagraph,
              ul: MdUl,
              ol: MdOl,
              li: MdListItem,
              strong: MdStrong,
              em: MdEm,
              blockquote: ({ children }) => (
                <blockquote className="my-3 rounded-r-xl border-l-3 border-orange-400 bg-orange-50/50 py-2 px-3.5 text-sm text-slate-700">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="my-3 overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-2xs">
                  <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {children}
                </thead>
              ),
              tbody: ({ children }) => (
                <tbody className="divide-y divide-slate-100 bg-white">
                  {children}
                </tbody>
              ),
              tr: ({ children }) => (
                <tr className="even:bg-slate-50/40 hover:bg-orange-50/30 transition-colors">
                  {children}
                </tr>
              ),
              th: ({ children }) => (
                <th className="px-3.5 py-2.5 font-semibold text-slate-600">
                  {children}
                </th>
              ),
              td: ({ children }) => {
                const rawText = flattenChildrenText(children).trim();
                const status = extractLeadingStatus(rawText);
                if (status) {
                  return (
                    <td className="px-3.5 py-2.5 align-middle text-slate-700 tabular-nums">
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        <StatusBadge
                          tone={status.tone}
                          icon={status.icon}
                          label={status.badgeText}
                        />
                        {status.restText && <span>{status.restText}</span>}
                      </span>
                    </td>
                  );
                }
                return (
                  <td className="px-3.5 py-2.5 align-middle text-slate-700 tabular-nums">
                    {withLeadingChip(children)}
                  </td>
                );
              },
              code: ({ className, children }) => {
                const raw = flattenChildrenText(children);
                const isBlock = Boolean(className) || raw.includes("\n");
                if (!isBlock) {
                  const bar = parseAsciiProgressBar(raw);
                  if (bar) {
                    return <SunsetProgressBar percent={bar.percent} />;
                  }
                  return (
                    <code className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-sm text-slate-800">
                      {children}
                    </code>
                  );
                }
                return (
                  <pre className="my-2 overflow-x-auto rounded-xl border border-slate-200 bg-slate-900 p-3 font-mono text-sm text-slate-100">
                    <code>{children}</code>
                  </pre>
                );
              },
            }}
          >
            {seg.content}
          </ReactMarkdown>
        );
      })}
    </div>
    </BulletContext.Provider>
  );
}
