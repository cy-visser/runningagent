import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DEMO_RACE_PREDICTOR_RESPONSE } from "../../demo/fixtures";
import * as api from "../../shared/api";
import { RacePredictorPanel } from "./RacePredictorPanel";

describe("RacePredictorPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders active sub-goal projection, North Star equivalent, 12-week drivers, and refreshes on click", async () => {
    const fetchSpy = vi
      .spyOn(api, "fetchRacePredictor")
      .mockResolvedValue(DEMO_RACE_PREDICTOR_RESPONSE);
    const refreshedPayload = structuredClone(DEMO_RACE_PREDICTOR_RESPONSE);
    refreshedPayload.cached = false;
    refreshedPayload.data!.projection!.race_day_s = 5140; // 1:25:40
    const refreshSpy = vi
      .spyOn(api, "refreshRacePredictor")
      .mockResolvedValue(refreshedPayload);

    render(
      <RacePredictorPanel
        open={true}
        onClose={vi.fn()}
        onSetGoalInProfile={vi.fn()}
        onBuildPlan={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
      />,
    );

    expect(await screen.findByText(/Sub-Goal 2 of 2 · Working Towards/i)).toBeInTheDocument();
    expect(screen.getByText("Sub-1:26 Half Marathon")).toBeInTheDocument();
    expect(screen.getByText("1:26:08")).toBeInTheDocument();
    expect(screen.getByText(/Sub-2:58 Marathon/)).toBeInTheDocument();
    expect(screen.getByText(/Threshold 3 x 10'/i)).toBeInTheDocument();
    expect(screen.getByText("Threshold anchor")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));
    await waitFor(() => expect(refreshSpy).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("1:25:40")).toBeInTheDocument();
  });

  it("tells the runner to first set a goal in Profile and then build a plan when no active goal is set", async () => {
    vi.spyOn(api, "fetchRacePredictor").mockResolvedValue({
      status: "no_goal",
      reason: "no_goal",
      tp_connected: true,
      cached: false,
      active_goal: null,
      data: null,
    });
    const onSetGoalInProfile = vi.fn();
    const onBuildPlan = vi.fn();

    render(
      <RacePredictorPanel
        open={true}
        onClose={vi.fn()}
        onSetGoalInProfile={onSetGoalInProfile}
        onBuildPlan={onBuildPlan}
        onOpenTrainingPeaks={vi.fn()}
      />,
    );

    expect(await screen.findByText("No active race goal set")).toBeInTheDocument();
    expect(
      screen.getByText(/First set a race goal \(or sub-goal roadmap\) in your Profile, and then build a training plan/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Set Goal in Profile/i }));
    expect(onSetGoalInProfile).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /^Build Plan$/i }));
    expect(onBuildPlan).toHaveBeenCalledTimes(1);
  });
});
