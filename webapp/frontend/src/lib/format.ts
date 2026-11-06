/**
 * Pure formatting and markdown helper utilities for durations, dates, status pills,
 * ASCII progress bars, and report table placeholders.
 */

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "—";
  }
  const total = Math.max(0, Math.round(seconds));
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hrs > 0) {
    return `${hrs}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

export function formatSignedGap(gapSeconds: number | null | undefined): {
  label: string;
  tone: "positive" | "warning" | "danger" | "neutral";
} {
  if (gapSeconds === null || gapSeconds === undefined || !Number.isFinite(gapSeconds)) {
    return { label: "No goal delta", tone: "neutral" };
  }
  const rounded = Math.round(gapSeconds);
  const absText = formatDuration(Math.abs(rounded));
  if (rounded <= -15) {
    return { label: `${absText} ahead of goal`, tone: "positive" };
  }
  if (rounded <= 20) {
    return {
      label: rounded === 0 ? "Right on goal" : `${rounded > 0 ? "+" : "-"}${absText} vs goal`,
      tone: "positive",
    };
  }
  if (rounded <= 90) {
    return { label: `+${absText} behind goal`, tone: "warning" };
  }
  return { label: `+${absText} behind goal`, tone: "danger" };
}

export function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const clean = iso.slice(0, 10);
  const parts = clean.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    return iso;
  }
  const [y, m, d] = parts;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatChartTickDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const clean = iso.slice(0, 10);
  const parts = clean.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    return clean;
  }
  const [y, m, d] = parts;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function greetingForHour(hour: number = new Date().getHours()): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export interface ParsedProgressBar {
  percent: number;
  label?: string;
}

const ASCII_BAR_RE = /^\[([█▓▒░=#\-.\s]{4,30})\]$/;

export function parseAsciiProgressBar(
  codeText: string,
  trailingContext?: string,
): ParsedProgressBar | null {
  const trimmed = codeText.trim();
  const match = ASCII_BAR_RE.exec(trimmed);
  if (!match) return null;

  const inner = match[1];
  const pctMatch = trailingContext ? /(\d{1,3})\s*%/.exec(trailingContext) : null;
  if (pctMatch) {
    const explicit = Math.min(100, Math.max(0, Number(pctMatch[1])));
    return { percent: explicit };
  }

  const chars = [...inner].filter((c) => !/\s/.test(c));
  if (chars.length === 0) return null;
  const filled = chars.filter((c) => c === "█" || c === "▓" || c === "=" || c === "#").length;
  const computed = Math.round((filled / chars.length) * 100);
  return { percent: Math.min(100, Math.max(0, computed)) };
}

export type StatusPillTone = "emerald" | "amber" | "rose" | "slate";

export interface LeadingStatusBadge {
  tone: StatusPillTone;
  badgeText: string;
  restText: string;
}

const LEADING_EMOJI_MAP: Record<string, StatusPillTone> = {
  "🟢": "emerald",
  "🟡": "amber",
  "🔴": "rose",
  "⚪": "slate",
};

export function extractLeadingStatus(text: string): LeadingStatusBadge | null {
  const trimmed = text.trim();
  for (const [emoji, tone] of Object.entries(LEADING_EMOJI_MAP)) {
    if (trimmed.startsWith(emoji)) {
      const after = trimmed.slice(emoji.length).trim();
      if (!after) {
        return { tone, badgeText: emoji, restText: "" };
      }
      const sepMatch =
        /^(.{1,32}?)(?:\s+(?:—|–|-|\||·)\s+|:\s+|[—–]\s*)(.+)$/.exec(after);
      if (sepMatch) {
        return {
          tone,
          badgeText: sepMatch[1].trim(),
          restText: sepMatch[2].trim(),
        };
      }
      if (after.length <= 28) {
        return { tone, badgeText: after, restText: "" };
      }
      return null;
    }
  }
  return null;
}

export function splitReportPlaceholders(
  markdown: string,
): Array<{ type: "markdown"; content: string } | { type: "placeholder"; token: string }> {
  const regex = /(\{\{(?:CHECKIN_TABLES|TREND_TABLES)\}\})/g;
  const parts = markdown.split(regex);
  const result: Array<
    { type: "markdown"; content: string } | { type: "placeholder"; token: string }
  > = [];
  for (const part of parts) {
    if (!part) continue;
    if (part === "{{CHECKIN_TABLES}}" || part === "{{TREND_TABLES}}") {
      result.push({ type: "placeholder", token: part });
    } else {
      result.push({ type: "markdown", content: part });
    }
  }
  return result;
}

export interface MarkdownSection {
  /** Heading text without markdown markers ("" for the preamble before the first heading). */
  title: string;
  /** Section body (markdown, without the heading line). */
  body: string;
  /** True when the section should render collapsed by default. */
  collapsible: boolean;
}

/** Check-in sections that start collapsed; Overview, Metrics Progress and Top 2 Priorities never match. */
const COLLAPSIBLE_SECTION_RE = /goal trajectory|training load|north star/i;

// `## Title` / `### Title`, or a whole-line bold title (`**🎯 Goal Trajectory Status**`, LLM drift).
// Bold lines only count when they name a known section: table labels such as
// `**Projection drivers:**` inside the metrics block must not start a new section.
const HEADING_RE = /^\s{0,3}#{1,4}\s+(.+?)\s*#*\s*$/;
const BOLD_HEADING_RE = /^\s{0,3}(?:\d+\.\s*)?\*\*([^*]+?)\*\*:?\s*$/;
const KNOWN_SECTION_RE = /overview|metrics progress|goal trajectory|training load|north star|priorit/i;

/**
 * Splits markdown into heading sections (fenced code blocks are never split).
 * Text before the first heading becomes an untitled, non-collapsible section.
 */
export function splitMarkdownSections(markdown: string): MarkdownSection[] {
  const sections: MarkdownSection[] = [];
  let title = "";
  let lines: string[] = [];
  let inFence = false;

  const flush = () => {
    const body = lines.join("\n").replace(/^\n+|\s+$/g, "");
    if (title || body) {
      sections.push({ title, body, collapsible: Boolean(title) && COLLAPSIBLE_SECTION_RE.test(title) });
    }
  };

  for (const line of markdown.split("\n")) {
    if (/^\s*```/.test(line)) inFence = !inFence;
    let match = inFence ? null : HEADING_RE.exec(line);
    if (!match && !inFence) {
      const bold = BOLD_HEADING_RE.exec(line);
      match = bold && KNOWN_SECTION_RE.test(bold[1]) ? bold : null;
    }
    if (match) {
      flush();
      title = match[1].replace(/\*\*/g, "").trim();
      lines = [];
    } else {
      lines.push(line);
    }
  }
  flush();
  return sections;
}

function stripInlineMarkdown(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`\[[█▓▒░=#\-.\s]+\]`/g, "")
    .replace(/[*_`]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** One-line teaser: the first sentence of prose, else the first table data row, else "". */
export function sectionTeaser(body: string): string {
  const lines = body.split("\n").map((l) => l.trim());
  let inFence = false;
  for (const line of lines) {
    if (line.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (inFence || !line || line.startsWith("|") || line.startsWith(">") || /^[-*_]{3,}$/.test(line)) {
      continue;
    }
    const prose = stripInlineMarkdown(line.replace(/^(?:[-*+]|\d+\.)\s+/, ""));
    if (prose) {
      const sentence = /^(.+?[.!?])(?:\s|$)/.exec(prose);
      return sentence ? sentence[1] : prose;
    }
  }
  const rows = lines.filter((l) => l.startsWith("|"));
  const dataRow = rows.find((row, idx) => idx > 0 && !/^\|[\s:|-]+\|?$/.test(row));
  if (dataRow) {
    return dataRow
      .split("|")
      .map((cell) => stripInlineMarkdown(cell))
      .filter(Boolean)
      .join(" · ");
  }
  return "";
}
