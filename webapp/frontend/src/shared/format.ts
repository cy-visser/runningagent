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

/** Icon keys for status badges; RichMarkdown maps them to lucide icons. */
export type StatusIconKey =
  | "check"
  | "alert"
  | "x"
  | "info"
  | "up"
  | "down"
  | "flat"
  | "dashed";

export interface LeadingStatusBadge {
  tone: StatusPillTone;
  badgeText: string;
  restText: string;
  /** Default icon for the emoji (check / alert / x / info). */
  icon: StatusIconKey;
}

export interface StatusEmojiInfo {
  tone: StatusPillTone;
  icon: StatusIconKey;
  /** True for the traffic-light circles (🟢 🟡 🔴 ⚪), which mark verdicts. */
  verdict: boolean;
}

const LEADING_EMOJI_MAP: Record<string, StatusEmojiInfo> = {
  "🟢": { tone: "emerald", icon: "check", verdict: true },
  "🟡": { tone: "amber", icon: "alert", verdict: true },
  "🔴": { tone: "rose", icon: "x", verdict: true },
  "⚪": { tone: "slate", icon: "info", verdict: true },
  "✅": { tone: "emerald", icon: "check", verdict: false },
  "⚠": { tone: "amber", icon: "alert", verdict: false },
  "❌": { tone: "rose", icon: "x", verdict: false },
};

/** Matches a leading status emoji (optionally followed by the U+FE0F variation selector). */
export const LEADING_STATUS_EMOJI_RE = /^\s*(🟢|🟡|🔴|⚪|✅|⚠|❌)\uFE0F?\s*/u;

/** Default icon for a tone (used when a caller gives no specific icon). */
export const DEFAULT_TONE_ICON: Record<StatusPillTone, StatusIconKey> = {
  emerald: "check",
  amber: "alert",
  rose: "x",
  slate: "info",
};

/** Tone/icon for a leading status emoji, and the text after it; null when there is none. */
export function matchLeadingStatusEmoji(
  text: string,
): (StatusEmojiInfo & { emoji: string; rest: string }) | null {
  const m = LEADING_STATUS_EMOJI_RE.exec(text);
  if (!m) return null;
  return { ...LEADING_EMOJI_MAP[m[1]], emoji: m[1], rest: text.slice(m[0].length) };
}

export function extractLeadingStatus(text: string): LeadingStatusBadge | null {
  const match = matchLeadingStatusEmoji(text.trim());
  if (!match) return null;
  const { tone, icon, emoji } = match;
  const after = match.rest.trim();
  if (!after) {
    return { tone, badgeText: emoji, restText: "", icon };
  }
  const sepMatch =
    /^(.{1,32}?)(?:\s+(?:—|–|-|\||·)\s+|:\s+|[—–]\s*)(.+)$/.exec(after);
  if (sepMatch) {
    return {
      tone,
      badgeText: sepMatch[1].trim(),
      restText: sepMatch[2].trim(),
      icon,
    };
  }
  if (after.length <= 28) {
    return { tone, badgeText: after, restText: "", icon };
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

/* ---------- LaTeX drift: the model sometimes writes $\text{VO}_2\text{max}$ despite the prompt ---------- */

const SUBSCRIPTS: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "-": "₋", "(": "₍", ")": "₎",
};
const SUPERSCRIPTS: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", "(": "⁽", ")": "⁾",
};
const LATEX_SYMBOLS: Record<string, string> = {
  rightarrow: "→", Rightarrow: "⇒", to: "→", leftarrow: "←", times: "×", approx: "≈", leq: "≤", le: "≤",
  geq: "≥", ge: "≥", pm: "±", cdot: "·", Delta: "Δ", sim: "~", degree: "°", circ: "°",
};
const LATEX_TEXT_CMD_RE = /\\(?:text|mathrm|textbf|mathbf|textit|operatorname)\s*\{([^{}]*)\}/g;
const LATEX_SYMBOL_RE = new RegExp(`\\\\(${Object.keys(LATEX_SYMBOLS).join("|")})(?![A-Za-z])`, "g");

function scriptChars(chars: string, map: Record<string, string>): string {
  return [...chars].every((c) => c in map) ? [...chars].map((c) => map[c]).join("") : chars;
}

/** Converts a LaTeX math fragment to readable plain text (best effort, never throws). */
function latexToText(math: string): string {
  return math
    .replace(LATEX_TEXT_CMD_RE, "$1")
    .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "$1/$2")
    .replace(/\\sqrt\s*\{([^{}]*)\}/g, "√$1")
    .replace(LATEX_SYMBOL_RE, (_, cmd: string) => LATEX_SYMBOLS[cmd])
    .replace(/\\([%$&#_])/g, "$1")
    .replace(/\\[,;:! ]/g, " ")
    .replace(/_\{([^{}]*)\}|_([A-Za-z0-9])/g, (_, a?: string, b?: string) => scriptChars(a ?? b ?? "", SUBSCRIPTS))
    .replace(/\^\{([^{}]*)\}|\^([A-Za-z0-9])/g, (_, a?: string, b?: string) => scriptChars(a ?? b ?? "", SUPERSCRIPTS))
    .replace(/\\([A-Za-z]+)/g, "$1")
    .replace(/[{}]/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

const LOOKS_LIKE_LATEX_RE = /\\[A-Za-z]|[_^]/;

function normalizeProse(text: string): string {
  return text
    // $$...$$ blocks first, then inline $...$ (no space just inside the dollars, so "$5 and $10" never pairs).
    .replace(/\$\$([\s\S]+?)\$\$/g, (m, inner: string) => (LOOKS_LIKE_LATEX_RE.test(inner) ? latexToText(inner) : m))
    .replace(/\$(?!\s)([^$\n]+?)(?<!\s)\$/g, (m, inner: string) => (LOOKS_LIKE_LATEX_RE.test(inner) ? latexToText(inner) : m))
    // Stray known commands outside $...$ (Markdown escapes like \* are not letters, so they stay).
    .replace(LATEX_TEXT_CMD_RE, "$1")
    .replace(LATEX_SYMBOL_RE, (_, cmd: string) => LATEX_SYMBOLS[cmd]);
}

/**
 * Cleans model formatting drift before rendering: LaTeX math becomes plain text / Unicode
 * (`$\text{VO}_2\text{max}$` -> `VO₂max`, `\rightarrow` -> `→`). Fenced and inline code are untouched.
 */
export function normalizeCoachMarkdown(markdown: string): string {
  if (!markdown.includes("\\") && !markdown.includes("$")) return markdown;
  return markdown
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/)
    .map((part, i) => (i % 2 === 1 ? part : normalizeProse(part)))
    .join("");
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
    const prose = stripInlineMarkdown(line.replace(/^(?:[-*+]|\d+\.)\s+/, ""))
      .replace(LEADING_STATUS_EMOJI_RE, "")
      .trim();
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
