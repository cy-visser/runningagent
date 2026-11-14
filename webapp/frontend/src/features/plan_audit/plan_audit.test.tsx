import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { DEMO_AUDIT_DATA, DEMO_AUDIT_MARKDOWN } from "../../demo/fixtures";
import { AuditReport } from "./AuditReport";

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

  it("uses generic chat sparkles/number pills for normal items and highlights ⚠️/🔴 issues", () => {
    const { unmount } = render(
      <AuditReport data={DEMO_AUDIT_DATA} markdown={DEMO_AUDIT_MARKDOWN} />,
    );
    const sparkles = screen.getAllByTestId("bullet-icon");
    // 2 positive Assessment bullets (depth 0) + Sub goal (0) + 2 sub-bullets (1, 1) + North star (0) + 1 sub-bullet (1)
    expect(sparkles.map((s) => s.dataset.depth)).toEqual([
      "0",
      "0",
      "0",
      "1",
      "1",
      "0",
      "1",
    ]);
    // The ⚠️ Travel & Achilles Watch bullet stands out as an amber issue callout row
    const issue = screen.getByTestId("issue-item");
    expect(issue).toHaveAttribute("data-tone", "amber");
    expect(issue).toHaveTextContent("Travel & Achilles Watch");
    expect(document.querySelector("[data-spacing=relaxed]")).not.toBeNull();
    expect(screen.queryByTestId("status-chip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-icon")).not.toBeInTheDocument();
    unmount();

    render(
      <AuditReport
        data={DEMO_AUDIT_DATA}
        markdown={"### Assessment\n- 🟢 Spacing solid\n- 🔴 **Spacing conflict:** < 14 h gap\n\n### Recommendations\n1. Cap tempo\n2. Hold 24 km"}
      />,
    );
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(1);
    expect(screen.getByTestId("issue-item")).toHaveAttribute("data-tone", "rose");
    expect(screen.getAllByTestId("number-badge").map((n) => n.textContent)).toEqual(["1", "2"]);
    expect(screen.queryByTestId("status-chip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-icon")).not.toBeInTheDocument();
  });
});

describe("AuditCharts calendar", () => {
  it("renders a week × weekday calendar with session cards, week totals, and factual % vs prior (no synthetic targets)", async () => {
    const { default: AuditCharts } =
      await vi.importActual<typeof import("./AuditCharts")>("./AuditCharts");
    render(<AuditCharts weeks={DEMO_AUDIT_DATA.weeks} today="2026-11-06" />);

    for (const d of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) {
      expect(screen.getByRole("columnheader", { name: d })).toBeInTheDocument();
    }
    // <= 4 weeks: no pager buttons, one header row + 4 week rows
    expect(screen.queryByTestId("agenda-pager")).not.toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(
      DEMO_AUDIT_DATA.weeks.length + 1,
    );

    expect(screen.getByText("Progressive Long Run 24 km")).toBeInTheDocument();
    expect(screen.getAllByText("Rest").length).toBeGreaterThan(0);
    expect(screen.getByText("73.5 km")).toBeInTheDocument();
    expect(screen.getByText("TSS 472")).toBeInTheDocument();
    // Factual week-over-week change (% vs prior), never synthetic Target X km ticks or captions.
    const vsPriors = screen.getAllByTestId("vs-prior");
    expect(vsPriors.map((v) => v.textContent)).toEqual([
      "+5% vs prior",
      "-3% vs prior",
      "+6% vs prior",
      "-24% vs prior",
    ]);
    expect(screen.queryByTestId("volume-target")).not.toBeInTheDocument();
    expect(screen.queryByTestId("volume-tick")).not.toBeInTheDocument();
    expect(screen.queryByTestId("volume-caption")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly km target")).not.toBeInTheDocument();
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

  it("pages by 4 weeks with Previous/Next arrows when auditing more than 4 weeks", async () => {
    const { default: AuditCharts } =
      await vi.importActual<typeof import("./AuditCharts")>("./AuditCharts");
    const tenWeeks = Array.from({ length: 10 }, (_, i) => {
      const start = new Date(Date.UTC(2026, 10, 30 + i * 7)).toISOString().slice(0, 10);
      return {
        ...DEMO_AUDIT_DATA.weeks[0],
        week: start,
        date_range: `Week ${i + 1}`,
        km: 50 + i * 2,
        vs_prior_pct: i === 0 ? null : 4,
        sessions: [
          {
            date: start,
            sport: "Run",
            title: `Block Run W${i + 1}`,
            category: "easy" as const,
            km: 10,
            minutes: 50,
            tss: 55,
            completed: false,
          },
        ],
      };
    });

    render(<AuditCharts weeks={tenWeeks} today="2026-11-13" />);

    expect(screen.getByTestId("agenda-pager")).toBeInTheDocument();
    expect(screen.getByText("Weeks 1–4 of 10")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(5); // 1 header + 4 week rows
    expect(screen.getByText("Block Run W1")).toBeInTheDocument();
    expect(screen.getByText("Block Run W4")).toBeInTheDocument();
    expect(screen.queryByText("Block Run W5")).not.toBeInTheDocument();
    // Week 1 has null vs_prior_pct -> only Weeks 2-4 render % vs prior on page 1
    expect(screen.getAllByTestId("vs-prior")).toHaveLength(3);

    const prev = screen.getByRole("button", { name: "Previous 4 weeks" });
    const next = screen.getByRole("button", { name: "Next 4 weeks" });
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();

    fireEvent.click(next);
    expect(screen.getByText("Weeks 5–8 of 10")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.getByText("Block Run W5")).toBeInTheDocument();
    expect(screen.getByText("Block Run W8")).toBeInTheDocument();

    fireEvent.click(next);
    expect(screen.getByText("Weeks 9–10 of 10")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3); // 1 header + 2 remaining week rows
    expect(screen.getByText("Block Run W9")).toBeInTheDocument();
    expect(screen.getByText("Block Run W10")).toBeInTheDocument();
    expect(next).toBeDisabled();

    fireEvent.click(prev);
    expect(screen.getByText("Weeks 5–8 of 10")).toBeInTheDocument();
  });
});
