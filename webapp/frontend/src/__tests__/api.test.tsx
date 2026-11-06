import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { Dashboard } from "../components/Dashboard";
import { DEMO_ME_ONBOARDING, DEMO_ME_READY } from "../demo/fixtures";
import { ApiError, fetchMe, onSessionExpired, parseSseFrame } from "../lib/api";

describe("api client & dashboard states", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    onSessionExpired(null);
  });

  it("parses SSE frames and ignores keepalive comments", () => {
    expect(parseSseFrame(": keepalive")).toBeNull();
    expect(
      parseSseFrame(
        'event: tool\ndata: {"name":"fetch_checkin_data","label":"Pulling data","state":"start"}',
      ),
    ).toEqual({
      event: "tool",
      data: {
        name: "fetch_checkin_data",
        label: "Pulling data",
        state: "start",
      },
    });
  });

  it("attaches X-Requested-With header and triggers session-expired listener on 401", async () => {
    const expiredSpy = vi.fn();
    onSessionExpired(expiredSpy);

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "IAP expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(fetchMe()).rejects.toBeInstanceOf(ApiError);
    expect(expiredSpy).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Requested-With": "XMLHttpRequest",
        }),
      }),
    );
  });

  it("renders Onboarding box for first-time user", () => {
    render(
      <Dashboard
        me={DEMO_ME_ONBOARDING}
        messages={[]}
        streaming={false}
        onSendPrompt={vi.fn()}
        onViewProfile={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
      />,
    );
    expect(screen.getByText("Onboarding")).toBeInTheDocument();
    expect(
      screen.getByText(/Start Onboarding — Connect TrainingPeaks/i),
    ).toBeInTheDocument();
  });

  it("renders 4 action cards including Trend Analysis (6 months) and Audit Schedule button for ready user", () => {
    render(
      <Dashboard
        me={DEMO_ME_READY}
        messages={[]}
        streaming={false}
        onSendPrompt={vi.fn()}
        onViewProfile={vi.fn()}
        onOpenTrainingPeaks={vi.fn()}
      />,
    );
    expect(screen.getByText("Profile")).toBeInTheDocument();
    expect(screen.getByText("Analyze Today's Run")).toBeInTheDocument();
    expect(screen.getByText("Check-In Report")).toBeInTheDocument();
    expect(screen.getByText("Trend Analysis")).toBeInTheDocument();
    expect(
      screen.getByText(/Last 6 months · progress, load capacity, pacing/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Audit Schedule – Current Week"),
    ).toBeInTheDocument();
    expect(screen.getByText("AI Running Coach")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Ask your running coach anything/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Coaching conversation"),
    ).not.toBeInTheDocument();
  });
});
