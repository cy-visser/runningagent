import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { Dashboard } from "./Dashboard";
import { DEMO_ME_ONBOARDING, DEMO_ME_READY } from "../demo/fixtures";
import * as api from "../shared/api";
import { ApiError, fetchMe, onSessionExpired, parseSseFrame } from "../shared/api";

describe("app shell & conversation lifecycle", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    onSessionExpired(null);
  });

  it("handles SSE parsing, 401 session expiry, dashboard onboarding/ready states, and full conversation lifecycle", async () => {
    // 1. SSE frame parsing & keepalive comments
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

    // 2. X-Requested-With header & 401 session-expired listener
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
    onSessionExpired(null);
    fetchMock.mockRestore();

    // 3. Dashboard onboarding state
    const { unmount: unmountOnboarding } = render(
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
    unmountOnboarding();

    // 4. App ready state & conversation lifecycle across quick actions, follow-ups, and New conversation
    vi.spyOn(api, "fetchMe").mockResolvedValue(DEMO_ME_READY);

    let sessionCounter = 0;
    const createNewSessionSpy = vi
      .spyOn(api, "createNewSession")
      .mockImplementation(async () => ({
        session_id: `fresh-${++sessionCounter}`,
        messages: [],
      }));

    let chatCounter = 0;
    const streamChatSpy = vi
      .spyOn(api, "streamChat")
      .mockImplementation(async (params, handlers) => {
        const sid = params.sessionId ?? `sess-${++chatCounter}`;
        handlers.onSession?.(sid);
        handlers.onMessage?.({ text: `Reply ${sid}`, kind: "chat" });
        handlers.onDone?.(sid);
      });

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Check-In Report")).toBeInTheDocument(),
    );
    expect(screen.getByText("Profile")).toBeInTheDocument();
    expect(screen.getByText("Analyze Today's Run")).toBeInTheDocument();
    expect(screen.getByText("Trend Analysis")).toBeInTheDocument();
    expect(
      screen.getByText(/Last 6 months · progress, load capacity, pacing/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Audit Schedule – Current Week"),
    ).toBeInTheDocument();

    // Clicking Check-In starts a new conversation (sessionId: null -> sess-1)
    fireEvent.click(screen.getByText("Check-In Report"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-1")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "Checking in", sessionId: null },
      expect.any(Object),
    );

    // Typing a follow-up in the composer reuses sess-1
    const textarea = screen.getByPlaceholderText(
      /Ask your running coach anything/i,
    );
    fireEvent.change(textarea, { target: { value: "What about Tuesday?" } });
    fireEvent.submit(textarea.closest("form")!);
    await waitFor(() =>
      expect(screen.getByText("What about Tuesday?")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "What about Tuesday?", sessionId: "sess-1" },
      expect.any(Object),
    );

    // Clicking another quick-action button clears the feed and starts a fresh session (sessionId: null -> sess-2)
    fireEvent.click(screen.getByText("Analyze Today's Run"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-2")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "Analyze today's run", sessionId: null },
      expect.any(Object),
    );
    expect(screen.queryByText("What about Tuesday?")).not.toBeInTheDocument();

    // Clicking "New conversation" creates a new session immediately via /api/session/new (fresh-1) and clears the feed
    fireEvent.click(screen.getByText("New conversation"));
    await waitFor(() => expect(createNewSessionSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Reply sess-2")).not.toBeInTheDocument();

    // Clicking a quick-action button on the already-empty feed uses fresh-1 without creating a duplicate session
    fireEvent.click(screen.getByText("Trend Analysis"));
    await waitFor(() =>
      expect(screen.getByText("Reply fresh-1")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      {
        message: "Trend analysis for the past 6 months",
        sessionId: "fresh-1",
      },
      expect.any(Object),
    );

    // Follow-up message continues fresh-1
    fireEvent.change(textarea, { target: { value: "And my easy pace?" } });
    fireEvent.submit(textarea.closest("form")!);
    await waitFor(() =>
      expect(screen.getByText("And my easy pace?")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "And my easy pace?", sessionId: "fresh-1" },
      expect.any(Object),
    );
  });
});
