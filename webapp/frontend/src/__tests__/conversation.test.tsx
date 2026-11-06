import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "../App";
import { DEMO_ME_READY } from "../demo/fixtures";
import * as api from "../lib/api";

describe("conversation lifecycle", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts a new conversation on every quick-action button and on New conversation, while keeping sessionId for typed follow-ups", async () => {
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

    // 1. Clicking Check-In starts a new conversation (sessionId: null -> sess-1)
    fireEvent.click(screen.getByText("Check-In Report"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-1")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "Checking in", sessionId: null },
      expect.any(Object),
    );

    // 2. Typing a follow-up in the composer reuses sess-1
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

    // 3. Clicking another quick-action button clears the feed and starts a fresh session (sessionId: null -> sess-2)
    fireEvent.click(screen.getByText("Analyze Today's Run"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-2")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      { message: "Analyze today's run", sessionId: null },
      expect.any(Object),
    );
    expect(screen.queryByText("What about Tuesday?")).not.toBeInTheDocument();

    // 4. Clicking "New conversation" creates a new session immediately via /api/session/new (fresh-1) and clears the feed
    fireEvent.click(screen.getByText("New conversation"));
    await waitFor(() => expect(createNewSessionSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Reply sess-2")).not.toBeInTheDocument();

    // 5. Clicking a quick-action button on the already-empty feed uses fresh-1 without creating a duplicate session
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

    // 6. Follow-up message continues fresh-1
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
