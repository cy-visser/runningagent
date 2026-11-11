import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { AppliedTrainingPlan, PlanWeek, StagedTrainingPlan } from "../../shared/types";
import { PlanStagedCard, weekHeadline } from "./PlanStagedCard";

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
      { date: start, day: "Mon", sport: "Strength", action: "create", title: `Strength W${n}`, duration_minutes: 45 },
      { date: start, day: "Tue", sport: "Run", action: "update", title: `Intervals W${n}`, distance_km: 11.04 },
      { date: start, day: "Wed", sport: "Bike", action: "delete", title: `Spin W${n}`, duration_minutes: 60 },
      { date: start, day: "Thu", sport: "Run", action: "keep", title: `Easy W${n}`, distance_km: 8 },
      { date: start, day: "Sun", sport: "Run", action: "create", title: `Long W${n}`, distance_km: 16 },
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

const shownWeeks = () => screen.getAllByTestId("plan-week").map((w) => w.textContent?.match(/^W(\d+)/)?.[1]);

describe("plan builder feature", () => {
  it("shows a 4-week window of compact week rows and pages with the arrows", () => {
    const onApply = vi.fn();
    render(<PlanStagedCard plan={plan()} status="pending" onApply={onApply} />);

    expect(screen.getByText("Proposed training plan")).toBeInTheDocument();
    expect(
      screen.getByText("Sub-3:20 Marathon · 24 weeks · 120 sessions (120 new · 18 updated · 10 removed · 5 kept)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Weeks 1–4 of 24")).toBeInTheDocument();
    expect(shownWeeks()).toEqual(["1", "2", "3", "4"]);
    // Never one long table: 4 weeks x 5 session chips.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("plan-session")).toHaveLength(20);

    const [w1] = screen.getAllByTestId("plan-week");
    expect(w1).toHaveTextContent("W1 · 30 Nov · Base · 43 km · TSS 290");
    const chips = within(w1).getAllByTestId("plan-session");
    expect(chips[0]).toHaveTextContent("MonNewStrength W145 min");
    expect(within(chips[0]).getByRole("img", { name: "Strength" })).toBeInTheDocument();
    expect(chips[1]).toHaveTextContent("TueUpdatedIntervals W111 km");
    expect(chips[2]).toHaveTextContent("Removed");
    expect(within(chips[2]).getByText("Spin W1")).toHaveClass("line-through");
    expect(chips[3]).toHaveTextContent("Kept");

    const prev = screen.getByRole("button", { name: "Previous 4 weeks" });
    const next = screen.getByRole("button", { name: "Next 4 weeks" });
    expect(prev).toBeDisabled();
    fireEvent.click(next);
    expect(screen.getByText("Weeks 5–8 of 24")).toBeInTheDocument();
    expect(shownWeeks()).toEqual(["5", "6", "7", "8"]);
    for (let i = 0; i < 4; i++) fireEvent.click(next);
    expect(screen.getByText("Weeks 21–24 of 24")).toBeInTheDocument();
    expect(next).toBeDisabled();
    fireEvent.click(prev);
    expect(shownWeeks()).toEqual(["17", "18", "19", "20"]);

    fireEvent.click(screen.getByRole("button", { name: /Apply to TrainingPeaks/ }));
    expect(onApply).toHaveBeenCalledWith(STAGED_ID);
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

    const chips = screen.getAllByTestId("plan-session");
    expect(chips[0]).toHaveTextContent("Tue07:00NewThreshold 2x15'12 km");
    expect(chips[1]).toHaveTextContent("Tue18:00New");

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
