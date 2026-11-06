import { describe, expect, it } from "vitest";
import {
  extractLeadingStatus,
  formatDuration,
  formatSignedGap,
  parseAsciiProgressBar,
  sectionTeaser,
  splitMarkdownSections,
  splitReportPlaceholders,
} from "../lib/format";

describe("format utilities", () => {
  it("formats race durations accurately", () => {
    expect(formatDuration(5124)).toBe("1:25:24");
    expect(formatDuration(2352)).toBe("39:12");
    expect(formatDuration(null)).toBe("—");
  });

  it("classifies signed race-goal gaps into coaching tones", () => {
    expect(formatSignedGap(-36)).toEqual({
      label: "0:36 ahead of goal",
      tone: "positive",
    });
    expect(formatSignedGap(0)).toEqual({
      label: "Right on goal",
      tone: "positive",
    });
    expect(formatSignedGap(55)).toEqual({
      label: "+0:55 behind goal",
      tone: "warning",
    });
    expect(formatSignedGap(180)).toEqual({
      label: "+3:00 behind goal",
      tone: "danger",
    });
  });

  it("parses inline ASCII progress bars into percentages", () => {
    expect(parseAsciiProgressBar("[████████░░]")?.percent).toBe(80);
    expect(parseAsciiProgressBar("[█████░░░░░]", " **58%**")?.percent).toBe(58);
    expect(parseAsciiProgressBar("Production_tpAuth")).toBeNull();
  });

  it("extracts leading semantic status emojis from table cells", () => {
    expect(extractLeadingStatus("🟢 On track — 36s buffer")).toEqual({
      tone: "emerald",
      badgeText: "On track",
      restText: "36s buffer",
    });
    expect(extractLeadingStatus("🟡 Monitor")).toEqual({
      tone: "amber",
      badgeText: "Monitor",
      restText: "",
    });
    expect(extractLeadingStatus("🟢 Sub-LT1 — 4:13/km pace")).toEqual({
      tone: "emerald",
      badgeText: "Sub-LT1",
      restText: "4:13/km pace",
    });
    expect(extractLeadingStatus("73.5 km")).toBeNull();
  });

  it("splits streaming report table placeholders cleanly", () => {
    const parts = splitReportPlaceholders("Intro\n\n{{CHECKIN_TABLES}}\n\nOutro");
    expect(parts).toEqual([
      { type: "markdown", content: "Intro\n\n" },
      { type: "placeholder", token: "{{CHECKIN_TABLES}}" },
      { type: "markdown", content: "\n\nOutro" },
    ]);
  });

  it("splits the check-in into sections and collapses only analysis sections", () => {
    const md = [
      "### Check-In Overview",
      "Solid block.",
      "### 📊 Metrics Progress",
      "**Projection drivers:**",
      "| a | b |",
      "|---|---|",
      "| 1 | 2 |",
      "**🎯 Goal Trajectory Status**",
      "🟢 On Track. More text.",
      "### 🔍 Training Load & Adaptation Analysis",
      "Balanced.",
      "### 🧭 North Star Progress",
      "Building.",
      "### 🚀 Top 2 Priorities for the Upcoming Week",
      "1. Long run.",
    ].join("\n");
    const sections = splitMarkdownSections(md);
    expect(sections.map((s) => [s.title, s.collapsible])).toEqual([
      ["Check-In Overview", false],
      ["📊 Metrics Progress", false],
      ["🎯 Goal Trajectory Status", true],
      ["🔍 Training Load & Adaptation Analysis", true],
      ["🧭 North Star Progress", true],
      ["🚀 Top 2 Priorities for the Upcoming Week", false],
    ]);
    expect(sections[1].body).toContain("**Projection drivers:**");   // table label is not a heading
  });

  it("keeps text before the first heading and ignores headings in code fences", () => {
    const sections = splitMarkdownSections("Intro line\n```\n### not a heading\n```\n### Goal Trajectory\nx");
    expect(sections[0]).toEqual({ title: "", body: "Intro line\n```\n### not a heading\n```", collapsible: false });
    expect(sections[1].title).toBe("Goal Trajectory");
  });

  it("builds a one-line teaser from prose, else the first table row", () => {
    expect(sectionTeaser("\n🟢 **On Track**. CTL is climbing [link](http://x). More.")).toBe("🟢 On Track.");
    expect(sectionTeaser("- **Balanced** load this week")).toBe("Balanced load this week");
    expect(sectionTeaser("| Metric | Value |\n|---|---|\n| **CTL** | 61.4 |")).toBe("CTL · 61.4");
    expect(sectionTeaser("")).toBe("");
  });
});
