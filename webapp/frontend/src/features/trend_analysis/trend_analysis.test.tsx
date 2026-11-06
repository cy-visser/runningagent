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
    });

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

  it("extends the long-run & volume readiness chart with the block's volume target path", async () => {
    const { readinessData, readinessSubtitle } =
      await vi.importActual<typeof import("./GoalCharts")>("./GoalCharts");
    const goal = DEMO_TREND_DATA.goal!;
    const data = readinessData(DEMO_TREND_DATA.weeks, goal.volume);
    // History weeks first, then the future weeks of the block carrying only a target.
    expect(data).toHaveLength(DEMO_TREND_DATA.weeks.length + 18);   // history ends 2026-10-26; plan starts 11-02
    const last = data[data.length - 1];
    expect(last).toMatchObject({ target: 56 });
    expect(last.km).toBeUndefined();
    expect(Math.max(...data.map((d) => d.target ?? 0))).toBe(94);
    // Every 4th build week dips to 80% of the ramp step.
    expect(goal.volume!.plan.filter((p) => p.phase === "recovery").map((p) => p.km)).toEqual([61, 66, 71]);
    // No computed long-run target: the coach reasons long runs, the chart shows the actual ones.
    expect(readinessSubtitle(goal.volume, 70)).toBe(
      "Longest run per week · volume 71 → 94 km/wk by Feb 15 (NS peak 110)",
    );
    // Without a volume target the proven level is shown, as before.
    expect(readinessSubtitle(null, 70)).toBe("Longest run per week · proven 70 km/wk");
  });
});
