import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { RichMarkdown } from "../../shared/RichMarkdown";
import type { AppliedTrainingPlan, PlanWeek, StagedTrainingPlan } from "../../shared/types";
import { PlanStagedCard, effectiveWeekStart, weekHeadline } from "./PlanStagedCard";

const STAGED_ID = "6b1e7c2a-4f0d-4a7e-9a35-2f1d8c9e0b11";

function week(n: number): PlanWeek {
  const start = new Date(Date.UTC(2026, 10, 30 + (n - 1) * 7)).toISOString().slice(0, 10);
  return {
    week: n,
    start,
    phase: n <= 8 ? "base" : "build",
    focus: "aerobic base; strength 2x",
    run_km: 42 + n,
    bike_minutes: 0,
    strength_sessions: 1,
    tss: 290,
    counts: { create: 2, update: 1, delete: 1, keep: 1 },
    rows: [
      { date: start, day: "Mon", sport: "Strength", category: "strength", action: "create", title: `Strength W${n}`, duration_minutes: 45 },
      { date: start, day: "Tue", sport: "Run", category: "quality", action: "update", title: `Intervals W${n}`, distance_km: 11.04 },
      { date: start, day: "Wed", sport: "Bike", category: "bike", action: "delete", title: `Spin W${n}`, duration_minutes: 60 },
      { date: start, day: "Thu", sport: "Run", category: "easy", action: "keep", title: `Easy W${n}`, distance_km: 8 },
      { date: start, day: "Sun", sport: "Run", category: "easy", action: "create", title: `Long W${n}`, distance_km: 16 },
    ],
  };
}

function plan(weeks = 24): StagedTrainingPlan {
  return {
    version: 1,
    staged_id: STAGED_ID,
    title: `Sub-3:20 Marathon · ${weeks} weeks`,
    mode: "new",
    start_date: "2026-11-30",
    end_date: "2027-05-16",
    totals: { weeks, sessions: weeks * 5, create: 120, update: 18, delete: 10, keep: 5 },
    weeks: Array.from({ length: weeks }, (_, i) => week(i + 1)),
  };
}

function applied(weeksDone: number[], extra: Partial<AppliedTrainingPlan> = {}): AppliedTrainingPlan {
  return {
    staged_id: STAGED_ID, total_weeks: 24, weeks_done: weeksDone, created: 0, updated: 0, deleted: 0,
    failed: 0, failed_weeks: [], done: false, ...extra,
  };
}

const shownWeeks = () =>
  screen.getAllByTestId("plan-week").map((w) => within(w).getByRole("rowheader").textContent?.match(/^W(\d+)/)?.[1]);

describe("plan builder agenda UI", () => {
  it("renders a Plan Audit-style 7-column Mon–Sun agenda grid with 4-week paging (no Show all button)", () => {
    const onApply = vi.fn();
    render(<PlanStagedCard plan={plan()} status="pending" onApply={onApply} />);

    expect(screen.getByText("Proposed training plan")).toBeInTheDocument();
    expect(
      screen.getByText("Sub-3:20 Marathon · 24 weeks · 120 sessions (120 new · 18 updated · 10 removed · 5 kept)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Weeks 1–4 of 24")).toBeInTheDocument();
    expect(shownWeeks()).toEqual(["1", "2", "3", "4"]);
    expect(screen.queryByTestId("plan-toggle-all")).not.toBeInTheDocument();
    expect(screen.queryByText(/Show all/i)).not.toBeInTheDocument();

    // 7-day Mon–Sun agenda table (header row + 4 visible week rows).
    expect(screen.getByRole("table", { name: "Proposed weekly schedule" })).toBeInTheDocument();
    for (const d of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Total"]) {
      expect(screen.getByRole("columnheader", { name: d })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.getAllByTestId("plan-session")).toHaveLength(20);
    // Rest days (Fri & Sat) show "Rest" just like Plan Audit.
    expect(screen.getAllByText("Rest")).toHaveLength(8);

    const [w1] = screen.getAllByTestId("plan-week");
    expect(within(w1).getByRole("rowheader")).toHaveTextContent("W1 · 30 NovBase");
    expect(w1).toHaveTextContent("43.0 km");
    expect(w1).toHaveTextContent("TSS 290");

    const cards = within(w1).getAllByTestId("plan-session");
    expect(cards[0]).toHaveAttribute("data-category", "strength");
    expect(within(cards[0]).getByRole("img", { name: "Strength" })).toBeInTheDocument();
    expect(cards[0]).toHaveTextContent("Strength W1");
    expect(cards[0]).toHaveTextContent("45 min");
    expect(cards[0]).toHaveTextContent("New");

    expect(cards[1]).toHaveAttribute("data-category", "quality");
    expect(cards[1]).toHaveTextContent("Intervals W1");
    expect(cards[1]).toHaveTextContent("11 km");
    expect(cards[1]).toHaveTextContent("Updated");

    expect(cards[2]).toHaveTextContent("Removed");
    expect(within(cards[2]).getByText("Spin W1")).toHaveClass("line-through");
    expect(cards[3]).toHaveTextContent("Kept");
    // Longest run of the week gets the LR badge.
    expect(cards[4]).toHaveTextContent("LR");

    // Pager navigation
    const prev = screen.getByRole("button", { name: "Previous 4 weeks" });
    const next = screen.getByRole("button", { name: "Next 4 weeks" });
    expect(prev).toBeDisabled();
    fireEvent.click(next);
    expect(screen.getByText("Weeks 5–8 of 24")).toBeInTheDocument();
    expect(shownWeeks()).toEqual(["5", "6", "7", "8"]);

    fireEvent.click(screen.getByRole("button", { name: /Apply to TrainingPeaks/ }));
    expect(onApply).toHaveBeenCalledWith(STAGED_ID);
  });

  it("renders concise Block Strategy and delta-only Plan Update messages with plain-chat pills (no status chips)", () => {
    const coachMessage = `### Block Strategy

13-week marathon build with a 3:1 load-to-recovery rhythm.

1. **Volume & Long Runs:** Ramps from **52 km** to **76 km/week** (W10) with a **32 km** long run, then a 2-week taper.
2. **Intensity & Rhythm:** Tuesday VO2max/threshold and Friday tempo stay separated by >= 48 h easy running (Monday rest).
3. **Strength & Cross-Training:** Heavy lower-body lifting pairs with Tuesday/Friday quality days so easy days stay easy.
4. **Watchpoints:**
   - Cap single-week volume jumps at <= 10% off your 48 km baseline.
   - Keep Wednesday recovery runs conversational below LT1.

- **13-week plan staged:** 96 sessions (96 new). Review the weeks below and press **Apply to TrainingPeaks**.`;

    const { unmount } = render(<RichMarkdown content={coachMessage} />);

    expect(screen.getByRole("heading", { name: "Block Strategy" })).toBeInTheDocument();
    expect(screen.getAllByTestId("number-badge").map((el) => el.textContent)).toEqual(["1", "2", "3", "4"]);
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(3);
    expect(screen.queryByTestId("status-badge")).not.toBeInTheDocument();
    expect(screen.queryByTestId("status-chip")).not.toBeInTheDocument();
    unmount();

    const updateMessage = `### Plan Update

Added Tilburg 10 Miles (W7) and Dam tot Damloop (W8) and moved @HM/@M work into Sunday long runs, capping quality at 12 km.

1. **Long-Run Quality Cap:** 15–16 km hard inside 25 km pushes weekly hard load past 25–30%; staged up to \`+12@HM\` in W10 instead (say the word if you still want 15–16 km).
2. **Weekly Rebalance:** Friday shifts to easy km (\`E 10–12\`) with lighter strength for >= 48 h recovery before Sunday.
3. **Back-to-Back Races:** Race Tilburg all-out (\`P 16k@HM\`), run W8 Tuesday easy, and treat Dam tot Dam as \`L 20 +10@M\`.

- **13-week plan staged:** 95 sessions (95 new). Review the weeks below and press **Apply to TrainingPeaks**.`;

    render(<RichMarkdown content={updateMessage} />);
    expect(screen.getByRole("heading", { name: "Plan Update" })).toBeInTheDocument();
    expect(screen.getAllByTestId("number-badge").map((el) => el.textContent)).toEqual(["1", "2", "3"]);
    expect(screen.getAllByTestId("bullet-icon")).toHaveLength(1);
    expect(screen.queryByTestId("status-chip")).not.toBeInTheDocument();
  });

  it("clamps W1 start label to plan.start_date and marks pre-start / post-end days outside window", () => {
    // Even if an older or mid-week plan has week.start on Monday (e.g. 2027-07-26) and start_date later (2027-07-28),
    // W1 displays 28 Jul (never 26 Jul) and Mon–Tue render as out-of-window '–'.
    const partialWeek: PlanWeek = {
      week: 1,
      start: "2027-07-26",
      phase: "base",
      focus: "opener",
      run_km: 26,
      tss: 150,
      rows: [
        { date: "2027-07-28", day: "Wed", sport: "Run", action: "create", title: "Easy Run 8 km", distance_km: 8 },
        { date: "2027-08-01", day: "Sun", sport: "Run", action: "create", title: "Long Run 18 km", distance_km: 18 },
      ],
    };
    expect(effectiveWeekStart(partialWeek, "2027-07-28")).toBe("2027-07-28");
    expect(weekHeadline(partialWeek, "2027-07-28")).toBe("W1 · 28 Jul · Base · 26 km · TSS 150");

    render(
      <PlanStagedCard
        plan={{
          ...plan(1),
          start_date: "2027-07-28",
          end_date: "2027-07-31",
          weeks: [partialWeek],
        }}
        status="pending"
        onApply={vi.fn()}
      />,
    );
    const header = screen.getByRole("rowheader");
    expect(header).toHaveTextContent("W1 · 28 JulBase");
    expect(header).not.toHaveTextContent("26 Jul");
    // Mon & Tue (< 28 Jul) are out-of-window ('–'); Thu–Sat are Rest.
    expect(document.querySelectorAll('[data-out-of-window="true"]')).toHaveLength(3); // Mon, Tue, and Sun > 31 Jul
    expect(screen.getAllByText("–")).toHaveLength(2); // Mon & Tue empty out-of-window cells
  });

  it("follows the week being applied with a progress bar, then shows applied", () => {
    const onApply = vi.fn();
    const p = plan();
    const { rerender } = render(
      <PlanStagedCard plan={p} status="applying" applied={applied([1, 2, 3, 4, 5])} applyingWeek={6} onApply={onApply} />,
    );
    expect(screen.getByText("Applying week 6 of 24…")).toBeInTheDocument();
    expect(screen.getByTestId("plan-progress")).toHaveStyle({ width: "21%" });
    expect(screen.getByText("Weeks 5–8 of 24")).toBeInTheDocument();
    const rows = screen.getAllByTestId("plan-week");
    expect(rows[0]).toHaveTextContent("Applied");
    expect(rows[1]).toHaveTextContent("Applying");
    expect(screen.getByRole("button", { name: /Applying…/ })).toBeDisabled();

    rerender(<PlanStagedCard plan={p} status="applying" applied={applied([1, 2, 3, 4, 5, 6, 7, 8])} applyingWeek={9} onApply={onApply} />);
    expect(screen.getByText("Weeks 9–12 of 24")).toBeInTheDocument();

    rerender(
      <PlanStagedCard plan={p} status="applied" applied={applied(p.weeks.map((w) => w.week), { done: true })} onApply={onApply} />,
    );
    expect(screen.getByText("Applied to TrainingPeaks")).toBeInTheDocument();
    expect(screen.queryByText(/Applying week/)).not.toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("offers Resume after a failed week and shows replaced plans without a button", () => {
    const onApply = vi.fn();
    const p = plan();
    const { rerender } = render(
      <PlanStagedCard plan={p} status="partial" applied={applied([1, 2], { failed: 1, failed_weeks: [3] })} onApply={onApply} />,
    );
    expect(screen.getByText(/2 of 24 weeks applied · failed: W3/)).toBeInTheDocument();
    expect(screen.getAllByTestId("plan-week")[2]).toHaveTextContent("Failed");
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    expect(onApply).toHaveBeenCalledWith(STAGED_ID);

    rerender(<PlanStagedCard plan={p} status="replaced" onApply={onApply} />);
    expect(screen.getByText("Replaced by a newer plan")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply|Resume/ })).not.toBeInTheDocument();

    rerender(<PlanStagedCard plan={p} status="pending" busy onApply={onApply} />);
    expect(screen.getByRole("button", { name: /Apply to TrainingPeaks/ })).toBeDisabled();
  });

  it("formats the week headline with bike minutes when planned", () => {
    expect(weekHeadline({ ...week(1), run_km: 42, bike_minutes: 45 })).toBe("W1 · 30 Nov · Base · 42 km · Bike 45 min · TSS 290");
  });
});

describe("plan builder: strength exercises and training times", () => {
  it("lists each planned strength session's exercises and shows double-day times", () => {
    const base = week(1);
    const doubleDay: PlanWeek = {
      ...base,
      rows: [
        { date: base.start, day: "Tue", sport: "Run", action: "create", title: "Threshold 2x15'", distance_km: 12, time: "07:00" },
        { date: base.start, day: "Tue", sport: "Strength", action: "create", title: "Strength: heavy lower body",
          duration_minutes: 40, time: "18:00", exercises: ["Back squat 4x5", "Deadlift 3x5"],
          load: "RPE 8 (2 reps in reserve) · rest 2-3'" },
        { date: base.start, day: "Fri", sport: "Strength", action: "delete", title: "Old gym", duration_minutes: 30,
          exercises: ["Leg press 3x10"] },
      ],
    };
    render(<PlanStagedCard plan={{ ...plan(1), weeks: [doubleDay] }} status="pending" onApply={vi.fn()} />);

    const cards = screen.getAllByTestId("plan-session");
    expect(cards[0]).toHaveTextContent("Threshold 2x15'");
    expect(cards[0]).toHaveTextContent("07:00");
    expect(cards[0]).toHaveTextContent("12 km");
    expect(cards[1]).toHaveTextContent("18:00");
    expect(cards[1]).toHaveTextContent("New");

    const section = screen.getByTestId("strength-exercises");
    expect(within(section).getByText("Strength exercises (1)")).toBeInTheDocument();
    const [session] = within(section).getAllByTestId("strength-session");
    expect(session).toHaveTextContent("Tue · 18:00 · Strength: heavy lower body · 40 min");
    expect(within(session).getByText("Back squat 4x5")).toBeInTheDocument();
    expect(within(session).getByText("RPE 8 (2 reps in reserve) · rest 2-3'")).toBeInTheDocument();
    expect(within(section).queryByText("Leg press 3x10")).not.toBeInTheDocument(); // removed sessions are not listed
  });

  it("shows no strength section when a week has no strength exercises", () => {
    render(<PlanStagedCard plan={plan(1)} status="pending" onApply={vi.fn()} />);
    expect(screen.queryByTestId("strength-exercises")).not.toBeInTheDocument();
  });
});
