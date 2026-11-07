import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { DEMO_WORKOUT_DATA, DEMO_WORKOUT_MARKDOWN } from "../../demo/fixtures";
import type { WorkoutReportData } from "../../shared/types";
import {
  WorkoutReport,
  formatWorkoutDate,
  splitTakeaways,
  stripSessionOverview,
} from "./WorkoutReport";

describe("workout analysis feature", () => {
  it("renders the session banner with tiles, elevation, HR zones, conditions and readiness", () => {
    render(<WorkoutReport data={DEMO_WORKOUT_DATA} markdown={DEMO_WORKOUT_MARKDOWN} />);
    const banner = screen.getByTestId("workout-banner");
    expect(within(banner).getByRole("heading", { name: "Tempo 3x10' @ Threshold" })).toBeInTheDocument();

    const meta = screen.getByTestId("workout-meta");
    expect(meta).toHaveTextContent("Wed 4 Nov 2026 · 07:12");
    expect(meta).toHaveTextContent("Amsterdam");
    expect(meta).toHaveTextContent("11°C (feels 9°C)");
    expect(meta).toHaveTextContent("78%");
    expect(meta).toHaveTextContent("14 km/h");
    expect(within(banner).getByText("Structured")).toBeInTheDocument();

    const tiles = screen.getAllByTestId("workout-tile");
    expect(tiles.map((t) => t.dataset.key)).toEqual(["distance", "duration", "pace", "hr", "tss", "decoupling"]);
    expect(tiles[2]).toHaveTextContent("NGP4:49/km");
    expect(tiles[3]).toHaveTextContent("max 176");

    expect(screen.getByRole("img", { name: "Elevation profile (+86 m / -84 m)" })).toBeInTheDocument();
    expect(screen.getAllByTestId("hr-zone-segment")).toHaveLength(5);
    expect(screen.getByTestId("hr-zones")).toHaveTextContent("Z4 33%");

    const chips = screen.getAllByTestId("readiness-chip");
    expect(chips.map((c) => c.dataset.key)).toEqual(["hrv", "rhr", "sleep"]);
    expect(chips[0]).toHaveAccessibleName("HRV 52 ms, up");
  });

  it("drops the coach's Session Overview but keeps the assessment headings and takeaways", () => {
    const { container } = render(<WorkoutReport data={DEMO_WORKOUT_DATA} markdown={DEMO_WORKOUT_MARKDOWN} />);
    expect(screen.queryByText("Session Overview")).not.toBeInTheDocument();
    expect(screen.queryByText(/Physiological Load/)).not.toBeInTheDocument();
    // The title heading duplicated by the banner is dropped too.
    expect(screen.getAllByRole("heading", { name: "Tempo 3x10' @ Threshold" })).toHaveLength(1);
    // Regression: "### 🎯 Execution…" directly followed by a "####" subsection must survive.
    expect(
      screen.getByRole("heading", { level: 3, name: "🎯 Execution & Physiological Assessment" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "Pacing & Quality Execution" })).toHaveClass("font-semibold");
    expect(
      screen.getByRole("heading", { level: 4, name: "Heart Rate Dynamics & Aerobic Stability" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "🚀 Key Takeaways & Adjustments" })).toBeInTheDocument();
    // The "---" rules sit at the edges of the assessment / takeaways parts, so they are trimmed.
    expect(container.querySelectorAll("hr")).toHaveLength(0);
    expect(screen.getAllByTestId("status-chip")).toHaveLength(3);
    const icons = screen.getAllByTestId("recommendation-icon");
    expect(icons.map((i) => i.dataset.icon)).toEqual(["subgoal", "northstar"]);
  });

  it("renders a bike banner without missing sections", () => {
    const bike: WorkoutReportData = {
      version: 1,
      workout_id: "b1",
      title: "Z2 Spin",
      sport: "Bike",
      sport_family: "bike",
      date: "2026-10-22",
      tiles: [
        { key: "distance", label: "Distance", value: "30.0", unit: "km" },
        { key: "power", label: "NP", value: "212", unit: "W" },
        { key: "if", label: "IF", value: "0.85" },
      ],
      elevation: null,
      hr_zones: null,
      weather: null,
      readiness: null,
    };
    render(<WorkoutReport data={bike} markdown="### 🎯 Execution\n* ✅ **Intensity:** steady." />);
    expect(screen.getAllByTestId("workout-tile").map((t) => t.dataset.key)).toEqual(["distance", "power", "if"]);
    expect(screen.queryByTestId("elevation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hr-zones")).not.toBeInTheDocument();
    expect(screen.queryByTestId("readiness-chip")).not.toBeInTheDocument();
    expect(screen.getByTestId("workout-meta")).toHaveTextContent("Thu 22 Oct 2026");
    expect(screen.queryByText("Structured")).not.toBeInTheDocument();
  });

  it("stripSessionOverview handles headings, bold pseudo-headings and missing sections", () => {
    expect(stripSessionOverview("### 🎯 Execution\n- a")).toBe("### 🎯 Execution\n- a");
    expect(
      stripSessionOverview("### 📋 Session Overview\n* **Volume:** 10 km\n\n### 🎯 Execution\n- a"),
    ).toBe("### 🎯 Execution\n- a");
    expect(
      stripSessionOverview("**Session Overview**\n* Volume: 10 km\n**🎯 Execution**\n- a"),
    ).toBe("**🎯 Execution**\n- a");
    expect(stripSessionOverview("## Easy Run\n### Session Overview\n* x\n### 🎯 Execution\n- a")).toBe(
      "### 🎯 Execution\n- a",
    );
    // Regression (Oct 15 reply): a heading directly followed by a subsection after the overview is kept.
    expect(
      stripSessionOverview(
        "### Session Overview\n* x\n\n---\n\n### 🎯 Execution\n\n#### Pacing & Quality Execution\ntext\n\n---\n\n### 🚀 Key Takeaways\n1. b",
      ),
    ).toBe("### 🎯 Execution\n\n#### Pacing & Quality Execution\ntext\n\n---\n\n### 🚀 Key Takeaways\n1. b");
    // Without an overview nothing is dropped, even a heading followed by a heading.
    expect(stripSessionOverview("### 🎯 Execution\n#### Pacing\ntext")).toBe("### 🎯 Execution\n#### Pacing\ntext");
    const { assessment, takeaways } = splitTakeaways("### 🎯 Execution\n- a\n\n---\n\n### 🚀 Key Takeaways\n1. b\n\n***");
    expect(assessment).toBe("### 🎯 Execution\n- a");
    expect(takeaways).toBe("### 🚀 Key Takeaways\n1. b");
    expect(formatWorkoutDate(null)).toBeNull();
  });
});
