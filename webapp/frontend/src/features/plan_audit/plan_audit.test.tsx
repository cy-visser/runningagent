import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { DEMO_AUDIT_DATA, DEMO_AUDIT_MARKDOWN } from "../../demo/fixtures";
import { AuditReport, splitRecommendations } from "./AuditReport";

vi.mock("./AuditCharts", () => ({
  default: () => <div data-testid="audit-charts" />,
}));

describe("plan audit feature", () => {
  it("renders AuditReport with weekly volume totals and assessment markdown", () => {
    render(
      <AuditReport data={DEMO_AUDIT_DATA} markdown={DEMO_AUDIT_MARKDOWN} />,
    );
    expect(screen.getByText("Plan Audit")).toBeInTheDocument();
    expect(screen.getByText("279.0 km total")).toBeInTheDocument();
    expect(screen.getByText("Assessment")).toBeInTheDocument();
    expect(screen.getByText("Recommendations")).toBeInTheDocument();
  });

  it("uses status chips for the assessment and goal icons for recommendations", () => {
    render(
      <AuditReport data={DEMO_AUDIT_DATA} markdown={DEMO_AUDIT_MARKDOWN} />,
    );
    expect(screen.getAllByTestId("status-chip")).toHaveLength(3);
    const icons = screen.getAllByTestId("recommendation-icon");
    expect(icons.map((i) => i.dataset.icon)).toEqual(["subgoal", "northstar"]);
    for (const icon of icons) {
      expect(icon.closest("li")).not.toHaveTextContent("Polarisation");
    }
  });

  it("splitRecommendations keeps everything in assessment without the heading", () => {
    expect(splitRecommendations("### Assessment\n- 🟢 ok")).toEqual({
      assessment: "### Assessment\n- 🟢 ok",
      recommendations: "",
    });
    const { assessment, recommendations } = splitRecommendations(
      "### Assessment\n- a\n\n### 💡 Recommendations\n- b",
    );
    expect(assessment).toBe("### Assessment\n- a");
    expect(recommendations).toBe("### 💡 Recommendations\n- b");
  });
});

describe("AuditCharts calendar", () => {
  it("renders a week × weekday calendar with session cards and week totals", async () => {
    const { default: AuditCharts } =
      await vi.importActual<typeof import("./AuditCharts")>("./AuditCharts");
    render(<AuditCharts weeks={DEMO_AUDIT_DATA.weeks} today="2026-11-06" />);

    for (const d of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) {
      expect(screen.getByRole("columnheader", { name: d })).toBeInTheDocument();
    }
    // One header row + one row per week
    expect(screen.getAllByRole("row")).toHaveLength(
      DEMO_AUDIT_DATA.weeks.length + 1,
    );

    expect(screen.getByText("Progressive Long Run 24 km")).toBeInTheDocument();
    expect(screen.getAllByText("Rest").length).toBeGreaterThan(0);
    expect(screen.getByText("73.5 km")).toBeInTheDocument();
    expect(screen.getByText("TSS 472")).toBeInTheDocument();
    // Planned weeks carry their weekly km target; the completed week has none.
    const targets = screen.getAllByTestId("volume-target");
    expect(targets.map((t) => t.textContent)).toEqual([
      "Target 72 km+1%",
      "Target 73 km-2%",
      "Target 75 km-15%",
    ]);
    // Gap tone: within ±10% is on track; the -15% week is below target (amber, not a red verdict).
    expect(targets.map((t) => t.getAttribute("data-tone"))).toEqual(["on", "on", "below"]);
    // Facts only (no coded ⚠ verdict): the coach judges the ramp.
    expect(targets[2]).toHaveAttribute(
      "title",
      "Weekly running-km target · planned -15% vs target · block target 94 km",
    );
    for (const t of targets) expect(t.getAttribute("title")).not.toMatch(/⚠/);
    // Bar shows planned km vs target with a tick per targeted week; legend explains the tick.
    expect(screen.getAllByTestId("volume-tick")).toHaveLength(3);
    expect(screen.getByText("Weekly km target")).toBeInTheDocument();
    // No volumeReference passed: no caption.
    expect(screen.queryByTestId("volume-caption")).not.toBeInTheDocument();
    expect(screen.getAllByText("LR")).toHaveLength(DEMO_AUDIT_DATA.weeks.length);

    // Today (Fri Nov 6) is highlighted and holds the planned strength session
    const todayCell = document.querySelector('[data-today="true"]') as HTMLElement;
    expect(todayCell).not.toBeNull();
    expect(
      within(todayCell).getByText("Heavy Calf + Single-leg RDL"),
    ).toBeInTheDocument();

    // Long-run lines and calendar notes are no longer rendered as text
    expect(screen.queryByText(/🏃/)).not.toBeInTheDocument();
    expect(screen.queryByText(/📝/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lisbon work trip/)).not.toBeInTheDocument();
  });

  it("explains the weekly km targets in a caption and badges recovery weeks", async () => {
    const { default: AuditCharts } =
      await vi.importActual<typeof import("./AuditCharts")>("./AuditCharts");
    const weeks = DEMO_AUDIT_DATA.weeks.map((w, i) =>
      i === 3 && w.volume
        ? { ...w, volume: { ...w.volume, phase: "recovery", target_km: 60, vs_path_pct: 22 } }
        : w,
    );
    render(
      <AuditCharts
        weeks={weeks}
        volumeReference={DEMO_AUDIT_DATA.volume_reference}
        today="2026-11-06"
      />,
    );

    expect(screen.getByTestId("volume-caption")).toHaveTextContent(
      "Weekly km targets ramp from your recent level (71 km/wk) to the 94 km/wk Half Marathon " +
        "block target (85% of your 110 km/wk Sub-2:58 Marathon peak). Every 4th week is a " +
        "recovery week. Targets are a reference, not a limit.",
    );
    const recovery = screen.getAllByTestId("volume-target")[2];
    expect(recovery).toHaveTextContent("Target 60 km+22%recovery");
    expect(recovery).toHaveAttribute("data-tone", "above");
    expect(recovery.getAttribute("title")).toMatch(/^Weekly running-km target \(recovery week\)/);
  });
});
