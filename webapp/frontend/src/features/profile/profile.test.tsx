import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

    fireEvent.click(screen.getByRole("button", { name: /Save Profile/i }));

    await waitFor(() => expect(updateProfileSpy).toHaveBeenCalledTimes(1));
    expect(updateProfileSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        location: "Utrecht, Netherlands",
        goal_type: "plan",
      }),
    );
    expect(onProfileUpdated).toHaveBeenCalledWith(DEMO_PROFILE_RESPONSE);
  });
});
