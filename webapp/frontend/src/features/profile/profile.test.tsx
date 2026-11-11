import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DEMO_PROFILE_RESPONSE } from "../../demo/fixtures";
import * as api from "../../shared/api";
import { ProfilePanel } from "./ProfilePanel";

describe("profile feature", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads runner profile in edit mode and submits updated fields via updateProfile", async () => {
    vi.spyOn(api, "fetchProfile").mockResolvedValue(DEMO_PROFILE_RESPONSE);
    const updateProfileSpy = vi
      .spyOn(api, "updateProfile")
      .mockResolvedValue(DEMO_PROFILE_RESPONSE);
    const onProfileUpdated = vi.fn();

    render(
      <ProfilePanel
        open={true}
        initialMode="edit"
        email="cyrille@cyvisser.altostrat.com"
        initials="CV"
        onClose={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
        onProfileUpdated={onProfileUpdated}
      />,
    );

    const locationInput = await screen.findByPlaceholderText(
      "Amsterdam, Netherlands",
    );
    fireEvent.change(locationInput, {
      target: { value: "Utrecht, Netherlands" },
    });
    // Mark the first block and the north star as planned (their plans are already in TrainingPeaks).
    fireEvent.click(screen.getByLabelText("Block 1 planned"));
    fireEvent.click(screen.getByLabelText("North star planned"));

    fireEvent.click(screen.getByRole("button", { name: /Save Profile/i }));

    await waitFor(() => expect(updateProfileSpy).toHaveBeenCalledTimes(1));
    expect(updateProfileSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        location: "Utrecht, Netherlands",
        goal_type: "plan",
        north_star: expect.objectContaining({ planned: true }),
      }),
    );
    const payload = updateProfileSpy.mock.calls[0][0];
    expect(payload.sub_goals[0].planned).toBe(true);
    expect(payload.sub_goals.slice(1).every((sg) => sg.planned === false)).toBe(true);
    expect(onProfileUpdated).toHaveBeenCalledWith(DEMO_PROFILE_RESPONSE);
  });
});

describe("profile training times", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requires run and strength times before saving and sends them in the payload", async () => {
    const withoutTimes = structuredClone(DEMO_PROFILE_RESPONSE);
    withoutTimes.profile.run_time_of_day = null;
    withoutTimes.profile.strength_time_of_day = null;
    vi.spyOn(api, "fetchProfile").mockResolvedValue(withoutTimes);
    const updateProfileSpy = vi.spyOn(api, "updateProfile").mockResolvedValue(DEMO_PROFILE_RESPONSE);

    render(
      <ProfilePanel
        open={true}
        initialMode="edit"
        email="cyrille@cyvisser.altostrat.com"
        initials="CV"
        onClose={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
        onProfileUpdated={vi.fn()}
      />,
    );

    const runGroup = await screen.findByRole("radiogroup", { name: "Run" });
    fireEvent.click(screen.getByRole("button", { name: /Save Profile/i }));
    expect(
      await screen.findByText("Please choose when you prefer to run and to do strength training."),
    ).toBeInTheDocument();
    expect(updateProfileSpy).not.toHaveBeenCalled();

    fireEvent.click(within(runGroup).getByRole("radio", { name: "Morning" }));
    const strengthGroup = screen.getByRole("radiogroup", { name: "Strength" });
    fireEvent.click(within(strengthGroup).getByRole("radio", { name: "Evening" }));
    expect(within(runGroup).getByRole("radio", { name: "Morning" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: /Save Profile/i }));

    await waitFor(() => expect(updateProfileSpy).toHaveBeenCalledTimes(1));
    const payload = updateProfileSpy.mock.calls[0][0];
    expect(payload).toMatchObject({ run_time_of_day: "morning", strength_time_of_day: "evening" });
    expect(payload).not.toHaveProperty("cross_training_strength");
  });

  it("shows the training times on the profile view", async () => {
    vi.spyOn(api, "fetchProfile").mockResolvedValue(DEMO_PROFILE_RESPONSE);
    render(
      <ProfilePanel
        open={true}
        initialMode="view"
        email="cyrille@cyvisser.altostrat.com"
        initials="CV"
        onClose={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
        onProfileUpdated={vi.fn()}
      />,
    );
    expect(await screen.findByText("Run: Morning · Strength: Evening")).toBeInTheDocument();
  });
});
