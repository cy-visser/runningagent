import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { StagedChanges } from "../../shared/types";
import { StagedChangesCard } from "./StagedChangesCard";

const STAGED: StagedChanges = {
  staged_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
  changes: [
    {
      kind: "workout",
      action: "update",
      date: "2026-11-03",
      sport: "Run",
      title: "Threshold 4x2km",
      replaces_title: "Threshold 2 x 15'",
      replaces: {
        title: "Threshold 2 x 15'",
        date: "2026-11-03",
        sport: "Run",
        distance_km: 12.5,
        duration_minutes: 63,
        tss_planned: 78,
      },
      workout_id: "w111",
      distance_km: 12,
      duration_minutes: 64.6, // shown as 65 min
      tss_planned: 78.2, // shown as TSS 78, so not marked as changed vs 78
      structure_summary: "15' WU · 4× (2 km @ 4:45–4:52/km / 2' rec) · 10' CD",
    },
    {
      kind: "workout",
      action: "update",
      date: "2026-11-05",
      sport: "Strength",
      title: "General S&C Work",
      replaces_title: "General S&C Work",
      replaces: { title: "General S&C Work", date: "2026-11-07", sport: "Strength", tss_planned: 0 },
      workout_id: "w222",
      duration_minutes: 45,
      tss_planned: 0,
    },
    {
      kind: "workout",
      action: "create",
      date: "2026-11-04",
      sport: "Run",
      title: "Recovery Run",
      workout_id: null,
      distance_km: 6,
      duration_minutes: null,
      tss_planned: null,
    },
    { kind: "note", action: "create", date: "2026-11-04", title: "Travel: Milan" },
  ],
};

describe("workout creator feature", () => {
  it("shows each change as current vs proposed workout and applies the set with one click", () => {
    const onApply = vi.fn();
    render(<StagedChangesCard staged={STAGED} status="pending" onApply={onApply} />);

    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Change", "Date", "Current workout", "Proposed workout"]);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4); // header + 3 workouts

    const [, update, move, create] = rows;
    const [, , current, proposed] = within(update).getAllByRole("cell");
    expect(update).toHaveTextContent("Update");
    expect(current).toHaveTextContent("Threshold 2 x 15'");
    expect(current).toHaveTextContent("12.5 km · 63 min · TSS 78");
    expect(proposed).toHaveTextContent("Threshold 4x2km");
    expect(proposed).toHaveTextContent("12 km · 65 min · TSS 78");
    expect(proposed).toHaveTextContent("4× (2 km @ 4:45–4:52/km / 2' rec)");
    // Changed values are bold; unchanged ones (TSS 78) are not.
    expect(within(proposed).getByText("12 km")).toHaveClass("font-bold");
    expect(within(proposed).getByText("TSS 78")).not.toHaveClass("font-bold");

    expect(move).toHaveTextContent("Move");
    expect(within(move).getAllByRole("cell")[2]).toHaveTextContent("General S&C Work (Sat 07 Nov)");
    expect(within(move).getAllByRole("cell")[3]).toHaveTextContent("Strength · 45 min · TSS 0");

    expect(create).toHaveTextContent("Create");
    expect(within(create).getAllByRole("cell")[2]).toHaveTextContent("–");
    expect(within(create).getAllByRole("cell")[3]).toHaveTextContent("Recovery Run");
    expect(screen.getByText("Travel: Milan")).toBeInTheDocument();
    expect(screen.getByText(/4 changes/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Update TrainingPeaks/ }));
    expect(onApply).toHaveBeenCalledWith(STAGED.staged_id);
  });

  it("falls back to the replaced title for staged sets without a snapshot", () => {
    const legacy: StagedChanges = {
      staged_id: "x",
      changes: [{ ...STAGED.changes[0], replaces: undefined }],
    };
    render(<StagedChangesCard staged={legacy} status="pending" onApply={vi.fn()} />);
    const [, , current, proposed] = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(current).toHaveTextContent("Threshold 2 x 15'");
    expect(within(proposed).getByText("12 km")).not.toHaveClass("font-bold"); // nothing to compare against
  });

  it("shows what a moved session is on both sides (builder, else description)", () => {
    const moved: StagedChanges = {
      staged_id: "m",
      changes: [
        {
          kind: "workout",
          action: "update",
          date: "2026-11-26",
          sport: "Run",
          title: "6 km Easy + Strides",
          workout_id: "3937622120",
          distance_km: 6,
          duration_minutes: 36,
          tss_planned: 32,
          structure_summary: "6 km @ 5:55–6:25/km · 4× (20\" strides / 1' walk)",
          replaces: {
            title: "6 km Easy + Strides",
            date: "2026-11-25",
            sport: "Run",
            distance_km: 6,
            duration_minutes: 36,
            tss_planned: 32,
            structure_summary: "6 km @ 5:55–6:25/km · 4× (20\" strides / 1' walk)",
          },
        },
        {
          kind: "workout",
          action: "update",
          date: "2026-11-27",
          sport: "Strength",
          title: "Core",
          workout_id: "s1",
          description_summary: "3 rounds: plank, side plank, glute bridge",
          replaces: { title: "Core", date: "2026-11-24", sport: "Strength", description_summary: "3 rounds: plank, side plank, glute bridge" },
        },
      ],
    };
    render(<StagedChangesCard staged={moved} status="pending" onApply={vi.fn()} />);
    const [, run, core] = screen.getAllByRole("row");
    const [, , current, proposed] = within(run).getAllByRole("cell");
    expect(run).toHaveTextContent("Move");
    expect(current).toHaveTextContent("6 km Easy + Strides (Wed 25 Nov)");
    expect(current).toHaveTextContent("4× (20\" strides / 1' walk)");
    expect(proposed).toHaveTextContent("6 km · 36 min · TSS 32");
    expect(proposed).toHaveTextContent("4× (20\" strides / 1' walk)");
    expect(current).not.toHaveTextContent("Existing workout");
    const [, , coreCurrent, coreProposed] = within(core).getAllByRole("cell");
    expect(coreCurrent).toHaveTextContent("3 rounds: plank");
    expect(coreProposed).toHaveTextContent("3 rounds: plank");
  });

  it("shows applying, applied and replaced states without a clickable button", () => {
    const onApply = vi.fn();
    const { rerender } = render(
      <StagedChangesCard staged={STAGED} status="applying" onApply={onApply} />,
    );
    expect(screen.getByRole("button", { name: /Updating/ })).toBeDisabled();

    rerender(<StagedChangesCard staged={STAGED} status="applied" onApply={onApply} />);
    expect(screen.getByText("Applied to TrainingPeaks")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<StagedChangesCard staged={STAGED} status="replaced" onApply={onApply} />);
    expect(screen.getByText("Replaced by newer changes")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<StagedChangesCard staged={STAGED} status="pending" busy onApply={onApply} />);
    expect(screen.getByRole("button", { name: /Update TrainingPeaks/ })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();
  });
});
