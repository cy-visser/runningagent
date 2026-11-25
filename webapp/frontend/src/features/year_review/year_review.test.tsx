import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DEMO_AVAILABLE_YEARS, DEMO_YEAR_REVIEW_RESPONSE } from "../../demo/fixtures";
import * as api from "../../shared/api";
import type { YearReviewResponse } from "../../shared/types";
import YearReviewChart from "./YearReviewChart";
import { YearReviewModal, buildDiscussYearPrompt } from "./YearReviewModal";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function buildDemoYearResponse(year: number): YearReviewResponse {
  const base = DEMO_YEAR_REVIEW_RESPONSE.data!;
  const isComplete = year < 2026;
  const totalRunKm = year === 2025 ? 2140 : base.kpis.total_run_km;
  return {
    status: "ready",
    year,
    available_years: DEMO_AVAILABLE_YEARS,
    tp_connected: true,
    cached: true,
    data: {
      ...base,
      year,
      is_complete: isComplete,
      as_of_date: isComplete ? `${year}-12-31` : base.as_of_date,
      last_computed_date: isComplete ? `${year}-12-31` : base.last_computed_date,
      window: {
        start: `${year}-01-01`,
        end: isComplete ? `${year}-12-31` : base.window.end,
        year_end: `${year}-12-31`,
        weeks: isComplete ? 52 : base.window.weeks,
      },
      kpis: {
        ...base.kpis,
        total_run_km: totalRunKm,
      },
    },
  };
}

describe("YearReviewModal", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders calendar-year switcher (latest-first), split Refresh (incremental default + full), KPIs, races, peaks, heatmap, and Discuss", async () => {
    const fetchSpy = vi
      .spyOn(api, "fetchYearReview")
      .mockImplementation(async (year) => buildDemoYearResponse(year ?? 2026));
    const refreshSpy = vi
      .spyOn(api, "refreshYearReview")
      .mockImplementation(async (year) => ({
        ...buildDemoYearResponse(year ?? 2026),
        cached: false,
      }));
    const onDiscuss = vi.fn();
    const onClose = vi.fn();

    render(
      <YearReviewModal
        open={true}
        onClose={onClose}
        onOpenTrainingPeaks={vi.fn()}
        onDiscussWithCoach={onDiscuss}
      />,
    );

    expect((await screen.findAllByText("2,486 km")).length).toBeGreaterThanOrEqual(1);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(undefined);
    expect(screen.getByText("Annual Review")).toBeInTheDocument();
    expect(screen.getByText("2026 · In Progress")).toBeInTheDocument();

    // Multi-year switcher ordered latest-first: 2026, 2025, 2024, 2023
    const yearRail = screen.getByRole("group", { name: "Select calendar year" });
    const yearButtons = within(yearRail).getAllByRole("button");
    expect(yearButtons.map((b) => b.textContent?.slice(0, 4))).toEqual([
      "2026",
      "2025",
      "2024",
      "2023",
    ]);

    // Explicitly omitted sync plumbing copy (user feedback)
    expect(screen.queryByText(/Synced through/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/cached in Firestore/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Only workouts since last sync/i)).not.toBeInTheDocument();

    expect(screen.getByText("Zevenheuvelenloop Warm-Up 10K")).toBeInTheDocument();
    expect(screen.getByText("CPC Loop Den Haag Half Marathon")).toBeInTheDocument();
    expect(screen.getByText("Pace @ LT2 (Threshold)")).toBeInTheDocument();
    expect(screen.getByText("2026 Peak Performances")).toBeInTheDocument();
    expect(screen.getAllByText(/Profile PR/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("PR 1:26:50")).toBeInTheDocument();
    expect(screen.getByText("Year Best")).toBeInTheDocument();
    expect(screen.getByText("2026 Activity Heatmap (Jan 1 – Dec 31)")).toBeInTheDocument();

    // Monthly / Weekly chart toggle
    const weeklyBtn = await screen.findByRole("button", { name: "Weekly" }, { timeout: 4000 });
    fireEvent.click(weeklyBtn);
    expect(weeklyBtn).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Monthly" })).toHaveAttribute("aria-pressed", "false");

    // Primary Refresh button defaults to incremental
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(refreshSpy).toHaveBeenCalledWith(2026, "incremental"));

    // Split Refresh chevron menu offers Incremental (Default) and Full year refresh
    fireEvent.click(screen.getByRole("button", { name: "Refresh options" }));
    const menu = screen.getByRole("menu", { name: "Refresh mode" });
    expect(within(menu).getByText(/Incremental refresh/i)).toBeInTheDocument();
    expect(within(menu).getByText(/Default/i)).toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("menuitem", { name: /Full year refresh/i }));
    await waitFor(() => expect(refreshSpy).toHaveBeenCalledWith(2026, "full"));

    // Switch to 2025 -> fetches 2025 and displays Completed status
    fireEvent.click(yearButtons[1]);
    expect(await screen.findByText("2025 · Completed")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(2025);
    expect(screen.getAllByText("2,140 km").length).toBeGreaterThanOrEqual(1);

    // Switching back to 2026 uses modal session cache (no extra fetch)
    fireEvent.click(yearButtons[0]);
    expect(await screen.findByText("2026 · In Progress")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);

    // Discuss with Coach passes a grounded summary prompt
    fireEvent.click(screen.getByRole("button", { name: /Discuss/i }));
    expect(onDiscuss).toHaveBeenCalledTimes(1);
    const prompt = onDiscuss.mock.calls[0][0] as string;
    expect(prompt).toContain("2,486 km");
    expect(prompt).toContain("Zevenheuvelenloop Warm-Up 10K");

    // Escape closes the modal
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  }, 15000);

  it("handles tp_not_connected and empty states cleanly", async () => {
    const onConnect = vi.fn();
    vi.spyOn(api, "fetchYearReview").mockResolvedValue({
      status: "tp_not_connected",
      year: 2026,
      available_years: [],
      tp_connected: false,
      cached: false,
      data: null,
    });

    const { rerender } = render(
      <YearReviewModal
        open={true}
        onClose={vi.fn()}
        onOpenTrainingPeaks={onConnect}
      />,
    );

    expect(
      await screen.findByText(/Connect TrainingPeaks to build your Annual Review/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Connect TrainingPeaks/i }));
    expect(onConnect).toHaveBeenCalledTimes(1);

    vi.spyOn(api, "fetchYearReview").mockResolvedValue({
      status: "empty",
      year: 2026,
      available_years: [],
      tp_connected: true,
      cached: false,
      data: null,
    });
    rerender(
      <YearReviewModal
        open={false}
        onClose={vi.fn()}
        onOpenTrainingPeaks={onConnect}
      />,
    );
    rerender(
      <YearReviewModal
        open={true}
        onClose={vi.fn()}
        onOpenTrainingPeaks={onConnect}
      />,
    );
    expect(
      await screen.findByText(/No completed workouts found in 2026/i),
    ).toBeInTheDocument();
  });

  it("builds a concise discussion prompt covering calendar year, KPIs, CTL, races, and shifts", () => {
    const prompt = buildDiscussYearPrompt(DEMO_YEAR_REVIEW_RESPONSE.data!);
    expect(prompt).toContain("calendar year 2026 YTD annual review");
    expect(prompt).toContain("42 → 61");
    expect(prompt).toContain("Pace @ LT2 (Threshold)");
  });

  it("renders YearReviewChart and switches between Monthly and Weekly series", () => {
    const data = DEMO_YEAR_REVIEW_RESPONSE.data!;
    render(<YearReviewChart year={data.year} monthly={data.monthly} weekly={data.weekly} />);
    expect(screen.getByText(/2026 Running Volume/i)).toBeInTheDocument();
    expect(screen.getByText(/Monthly running km/i)).toBeInTheDocument();
    expect(screen.getByText("Peak CTL")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Weekly" }));
    expect(screen.getByText(/Weekly running km/i)).toBeInTheDocument();
  });
});
