import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { DEMO_TREND_DATA, DEMO_TREND_MARKDOWN } from "../../demo/fixtures";
import {
  extractLeadingStatus,
  formatDuration,
  parseAsciiProgressBar,
} from "../../shared/format";
import { TrendReport, ladderLevels } from "./TrendReport";

vi.mock("./TrendCharts", () => ({
  default: () => <div data-testid="trend-charts" />,
}));
vi.mock("./GoalCharts", () => ({
  default: () => <div data-testid="goal-charts" />,
}));

describe("trend analysis feature", () => {
  it("formats durations, status badges, and progress bars, and renders TrendReport", async () => {
    expect(formatDuration(5124)).toBe("1:25:24");
    expect(formatDuration(2352)).toBe("39:12");
    expect(formatDuration(null)).toBe("—");

    expect(parseAsciiProgressBar("[████████░░]")?.percent).toBe(80);
    expect(parseAsciiProgressBar("Production_tpAuth")).toBeNull();

    expect(extractLeadingStatus("🟢 On track — 36s buffer")).toEqual({
      tone: "emerald",
      badgeText: "On track",
      restText: "36s buffer",
      icon: "check",
    });
    expect(extractLeadingStatus("⚠️ Watch: Achilles")).toMatchObject({
      tone: "amber",
      badgeText: "Watch",
      icon: "alert",
    });
    expect(extractLeadingStatus("❌ Missed")).toMatchObject({ tone: "rose", icon: "x" });

    render(
      <TrendReport data={DEMO_TREND_DATA} markdown={DEMO_TREND_MARKDOWN} />,
    );
    expect(screen.getByText("Trend Analysis")).toBeInTheDocument();
    expect(screen.getByText("Last 6 months")).toBeInTheDocument();
    expect(screen.getByText("Chronic Load (CTL)")).toBeInTheDocument();

    // Header: projection toward the goal and the north star replaces the Proven / Peak pills.
    expect(screen.getByText("Sub-1:26 Half Marathon")).toBeInTheDocument();
    expect(screen.getByText("1:27:05")).toBeInTheDocument();
    expect(screen.getByText("+1:05 behind")).toBeInTheDocument();
    expect(screen.getByText("Sub-2:58 Marathon")).toBeInTheDocument();
    expect(screen.getByText("≈ 3:01:33")).toBeInTheDocument();
    expect(screen.queryByText(/Proven 70 km\/wk/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Peak /)).not.toBeInTheDocument();

    // Ladder: only the highest proven level and the grey next tier; target pills stay.
    const rows = screen.getAllByTestId("ladder-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("70+ km/wk");
    expect(rows[1]).toHaveTextContent("80+ km/wk");
    expect(rows[1]).toHaveTextContent("Next tier");
    expect(screen.getByText("100 km:", { exact: false })).toBeInTheDocument();

    // Training paces table and the LLM recommendations.
    expect(screen.getByText("Training Paces")).toBeInTheDocument();
    expect(screen.getByText("4:08/km")).toBeInTheDocument();
    expect(screen.getByText("🎯 Next Block: Top 3")).toBeInTheDocument();
    expect(screen.getByText("🧭 North Star")).toBeInTheDocument();
    expect(await screen.findByTestId("goal-charts")).toBeInTheDocument();
  });

  it("keeps only the highest proven level plus the next tier", () => {
    const lv = (level: number, proven: boolean, weeks = 3) => ({
      level, weeks, streak: weeks, tolerated_share: 1, proven,
    });
    expect(ladderLevels([]).length).toBe(0);
    // Nothing proven: only the lowest level that was run.
    expect(ladderLevels([lv(30, false), lv(40, false)]).map((l) => l.level)).toEqual([30]);
    // Next tier never run: a synthetic, empty grey row.
    const [top, next] = ladderLevels([lv(50, true), lv(60, true)]);
    expect(top.level).toBe(60);
    expect(next).toMatchObject({ level: 70, weeks: 0, proven: false });
  });

  it("builds the long-run & volume readiness chart from measured history and proven capacity", async () => {
    const { readinessData, readinessSubtitle } =
      await vi.importActual<typeof import("./GoalCharts")>("./GoalCharts");
    const data = readinessData(DEMO_TREND_DATA.weeks);
    expect(data).toHaveLength(DEMO_TREND_DATA.weeks.length);
    expect(data.every((d) => "km" in d && "long_km" in d && !("target" in d))).toBe(true);
    expect(readinessSubtitle(70)).toBe("Longest run per week · proven 70 km/wk");
    expect(readinessSubtitle(null)).toBe("Longest run per week");
  });
});
