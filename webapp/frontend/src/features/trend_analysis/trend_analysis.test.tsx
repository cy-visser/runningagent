import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { DEMO_TREND_DATA, DEMO_TREND_MARKDOWN } from "../../demo/fixtures";
import {
  extractLeadingStatus,
  formatDuration,
  parseAsciiProgressBar,
} from "../../shared/format";
import { TrendReport } from "./TrendReport";

vi.mock("./TrendCharts", () => ({
  default: () => <div data-testid="trend-charts" />,
}));

describe("trend analysis feature", () => {
  it("formats durations, status badges, and progress bars, and renders TrendReport", () => {
    expect(formatDuration(5124)).toBe("1:25:24");
    expect(formatDuration(2352)).toBe("39:12");
    expect(formatDuration(null)).toBe("—");

    expect(parseAsciiProgressBar("[████████░░]")?.percent).toBe(80);
    expect(parseAsciiProgressBar("Production_tpAuth")).toBeNull();

    expect(extractLeadingStatus("🟢 On track — 36s buffer")).toEqual({
      tone: "emerald",
      badgeText: "On track",
      restText: "36s buffer",
    });

    render(
      <TrendReport data={DEMO_TREND_DATA} markdown={DEMO_TREND_MARKDOWN} />,
    );
    expect(screen.getByText("Trend Analysis")).toBeInTheDocument();
    expect(screen.getByText("Last 6 months")).toBeInTheDocument();
    expect(screen.getByText("Chronic Load (CTL)")).toBeInTheDocument();
    expect(screen.getByText("6-Month Structural Progression")).toBeInTheDocument();
  });
});
