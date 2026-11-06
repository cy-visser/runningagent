import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DEMO_CHECKIN_DATA, DEMO_CHECKIN_MARKDOWN } from "../../demo/fixtures";
import {
  formatSignedGap,
  sectionTeaser,
  splitMarkdownSections,
  splitReportPlaceholders,
} from "../../shared/format";
import { CheckinReport } from "./CheckinReport";

vi.mock("./CheckinCharts", () => ({
  default: () => <div data-testid="checkin-charts" />,
}));

describe("check-in report feature", () => {
  it("parses check-in sections/teasers/gaps and renders CheckinReport with collapsible analysis sections", () => {
    // 1. Signed race-goal gap tones
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

    // 2. Placeholder & markdown section splitting + teaser generation
    expect(
      splitReportPlaceholders("Intro\n\n{{CHECKIN_TABLES}}\n\nOutro"),
    ).toEqual([
      { type: "markdown", content: "Intro\n\n" },
      { type: "placeholder", token: "{{CHECKIN_TABLES}}" },
      { type: "markdown", content: "\n\nOutro" },
    ]);

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
    expect(
      sectionTeaser("\n🟢 **On Track**. CTL is climbing [link](http://x). More."),
    ).toBe("🟢 On Track.");

    // 3. Render CheckinReport component and expand a collapsible analysis section
    render(
      <CheckinReport data={DEMO_CHECKIN_DATA} markdown={DEMO_CHECKIN_MARKDOWN} />,
    );
    expect(screen.getByText("61.4")).toBeInTheDocument();
    expect(screen.getByText("0:36 ahead of goal")).toBeInTheDocument();

    const goalToggle = screen.getByRole("button", {
      name: /Goal Trajectory Status/i,
    });
    expect(goalToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(goalToggle);
    expect(goalToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/leaves a 36 s buffer/i)).toBeInTheDocument();
  });
});
