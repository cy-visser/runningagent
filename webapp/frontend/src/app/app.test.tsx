import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "./App";
import { Dashboard, auditPlanAction, buildPlanAction } from "./Dashboard";
import { DEMO_ME_ONBOARDING, DEMO_ME_READY, DEMO_PLAN } from "../demo/fixtures";
import * as api from "../shared/api";
import { ApiError, fetchMe, onSessionExpired, parseSseFrame } from "../shared/api";
import type { AppliedTrainingPlan, QuickAction, StagedTrainingPlan } from "../shared/types";

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
      screen.getByText(auditPlanAction(DEMO_ME_READY.summary).title),
    ).toBeInTheDocument();
    // 6 equal cards: Profile, Analyze, Check-In, Trend, Audit Plan, Build Plan (no full-width CTA).
    const grid = screen.getByRole("region", { name: "Quick actions" });
    expect(within(grid).getAllByRole("button")).toHaveLength(6);
    expect(within(grid).getByText(/^Audit Plan – /)).toBeInTheDocument();
    expect(within(grid).getByText("Build Plan")).toBeInTheDocument();
    expect(
      within(grid).getByText(buildPlanAction(DEMO_ME_READY.summary).subtitle),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Audit Schedule/)).not.toBeInTheDocument();
    expect(grid.querySelector(".bg-sunset")).toBeNull();

    // Clicking Check-In starts a new conversation (sessionId: null -> sess-1)
    fireEvent.click(screen.getByText("Check-In Report"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-1")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      {
        message: "Checking in",
        sessionId: null,
        action: { skill: "check-in-report" },
      },
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

    // Clicking another quick-action button clears the feed, clears any typed draft, and starts a fresh session (sessionId: null -> sess-2)
    fireEvent.change(textarea, { target: { value: "unsent draft" } });
    fireEvent.click(screen.getByText("Analyze Today's Run"));
    await waitFor(() =>
      expect(screen.getByText("Reply sess-2")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      {
        message: "Analyze today's run",
        sessionId: null,
        action: { skill: "workout-analysis", date_str: "today", sport: "run" },
      },
      expect.any(Object),
    );
    expect(screen.queryByText("What about Tuesday?")).not.toBeInTheDocument();
    expect(textarea).toHaveValue("");

    // Clicking "New conversation" creates a new session immediately via /api/session/new (fresh-1),
    // clears the feed and the typed draft, and the button stays visible
    fireEvent.change(textarea, { target: { value: "another unsent draft" } });
    fireEvent.click(screen.getByText("New conversation"));
    await waitFor(() => expect(createNewSessionSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Reply sess-2")).not.toBeInTheDocument();
    expect(textarea).toHaveValue("");
    await waitFor(() =>
      expect(screen.getByText("New conversation").closest("button")).toBeEnabled(),
    );

    // Clicking it again on the already-fresh session only clears the draft — no duplicate session
    fireEvent.change(textarea, { target: { value: "draft on fresh session" } });
    fireEvent.click(screen.getByText("New conversation"));
    expect(textarea).toHaveValue("");
    expect(createNewSessionSpy).toHaveBeenCalledTimes(1);

    // Clicking a quick-action button on the already-empty feed uses fresh-1 without creating a duplicate session
    fireEvent.click(screen.getByText("Trend Analysis"));
    await waitFor(() =>
      expect(screen.getByText("Reply fresh-1")).toBeInTheDocument(),
    );
    expect(streamChatSpy).toHaveBeenLastCalledWith(
      {
        message: "Trend analysis for the past 6 months",
        sessionId: "fresh-1",
        action: { skill: "trend-analysis", weeks: 26 },
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

    // The top-left title goes home: scrolls to the top and focuses the coaching hub heading,
    // keeping the conversation.
    const scrollSpy = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: /go to coaching hub/i }));
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
    expect(document.activeElement).toBe(document.getElementById("coaching-hub"));
    expect(screen.getByText("And my easy pace?")).toBeInTheDocument();
  });
});

describe("auditPlanAction", () => {
  // Friday 2026-11-06 (local) -> Monday 2026-11-02; 8-week cap ends Sunday 2026-12-27.
  const now = new Date(2026, 10, 6, 12);
  const summary = (active_date: string | null, active_goal = "Sub-1:26 Half Marathon") => ({
    ...DEMO_ME_READY.summary!,
    active_goal,
    active_date,
  });

  it("falls back to the current-week audit without an upcoming race", () => {
    for (const s of [null, summary(null), summary("TBD"), summary("2026-11-05")]) {
      const action = auditPlanAction(s, now);
      expect(action.title).toBe("Audit Plan – Current Week");
      expect(action.prompt).toBe("Audit my plan for this week");
      expect(action.action).toEqual({ skill: "plan-audit" });
    }
  });

  it("audits from Monday of the current week until race day within 4 weeks", () => {
    const action = auditPlanAction(summary("2026-11-22"), now);
    expect(action.title).toBe("Audit Plan – Until Race Day");
    expect(action.action).toEqual({
      skill: "plan-audit",
      start_date: "2026-11-02",
      end_date: "2026-11-22",
    });
    // Dates travel as structured arguments, never as instructions for the LLM.
    expect(action.prompt).not.toContain("start_date=");
    expect(action.prompt).toContain("Sub-1:26 Half Marathon");
    expect(action.subtitle).toContain("Sub-1:26 Half Marathon");

    // Race today and race exactly on the cap boundary are both uncapped.
    expect(auditPlanAction(summary("2026-11-06"), now).action).toMatchObject({
      end_date: "2026-11-06",
    });
    expect(auditPlanAction(summary("2026-11-29"), now).title).toBe(
      "Audit Plan – Until Race Day",
    );
  });

  it("caps the window at 4 weeks for distant races", () => {
    const action = auditPlanAction(summary("2027-03-14"), now);
    expect(action.title).toBe("Audit Plan – Next 4 Weeks");
    expect(action.action).toEqual({
      skill: "plan-audit",
      start_date: "2026-11-02",
      end_date: "2026-11-29",
    });
    expect(action.prompt).toContain("race on 2027-03-14");
  });
});

describe("plan builder: Build Plan card and week-by-week apply loop", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("stages a plan, applies it with silent per-week turns, stops on a failed week and resumes", async () => {
    const plan: StagedTrainingPlan = {
      ...DEMO_PLAN,
      title: "Sub-1:26 Half Marathon · 6 weeks",
      totals: { ...DEMO_PLAN.totals, weeks: 6 },
      weeks: DEMO_PLAN.weeks.slice(0, 6),
    };
    const weeksDone: number[] = [];
    let failWeek3 = true;
    const gate: { release?: () => void } = {};
    const actions: Array<{ action?: QuickAction; sessionId?: string | null; message: string }> = [];

    vi.spyOn(api, "fetchMe").mockResolvedValue(DEMO_ME_READY);
    vi.spyOn(api, "streamChat").mockImplementation(async (params, handlers) => {
      const sid = params.sessionId ?? "plan-sess";
      actions.push({ action: params.action, sessionId: params.sessionId, message: params.message });
      handlers.onSession?.(sid);
      const a = params.action;
      if (a?.skill === "plan-builder") {
        handlers.onTool?.({ name: "stage_training_plan", label: "Building your plan", state: "done" });
        handlers.onPlanStaged?.(plan);
        handlers.onMessage?.({ text: "📋 6-week plan staged", kind: "chat" });
      } else if (a?.skill === "plan-builder:apply") {
        if (a.week === 1) await new Promise<void>((r) => (gate.release = r));
        const failed = a.week === 3 && failWeek3;
        if (failed) failWeek3 = false;
        else weeksDone.push(a.week);
        const state: AppliedTrainingPlan = {
          staged_id: plan.staged_id, total_weeks: 6, weeks_done: [...weeksDone], created: 0, updated: 0,
          deleted: 0, failed: failed ? 1 : 0, failed_weeks: failed ? [3] : [], done: weeksDone.length === 6,
        };
        handlers.onPlanApplied?.(state);
        if (state.done) handlers.onMessage?.({ text: "✅ TrainingPeaks updated: 6 weeks", kind: "chat" });
      }
      handlers.onDone?.(sid);
    });

    render(<App />);
    await waitFor(() => expect(screen.getByText("Build Plan")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Build Plan"));
    await waitFor(() => expect(screen.getByText("Proposed training plan")).toBeInTheDocument());
    expect(actions[0].action).toEqual(buildPlanAction(DEMO_ME_READY.summary).action);
    expect(screen.getByText("Weeks 1–4 of 6")).toBeInTheDocument();
    // "AI Running Coach" labels = top bar + one per assistant bubble.
    const coachBubbles = () => screen.getAllByText("AI Running Coach").length;
    const oneBubble = coachBubbles();

    // Apply: one user bubble, then silent per-week turns with live progress.
    fireEvent.click(screen.getByRole("button", { name: /Apply to TrainingPeaks/ }));
    await waitFor(() => expect(gate.release).toBeDefined());
    expect(screen.getByText("Applying week 1 of 6…")).toBeInTheDocument();
    expect(screen.getAllByText("Apply plan to TrainingPeaks")).toHaveLength(1);
    expect(coachBubbles()).toBe(oneBubble); // no empty assistant bubble for silent turns
    // The hub stays locked for the whole loop.
    expect(screen.getByText("Check-In Report").closest("button")).toBeDisabled();
    gate.release!();

    // Week 3 fails -> the loop stops and the card offers Resume.
    await waitFor(() => expect(screen.getByRole("button", { name: /Resume/ })).toBeInTheDocument());
    expect(actions.slice(1).map((c) => c.action)).toEqual([1, 2, 3].map((week) => ({
      skill: "plan-builder:apply", staged_id: plan.staged_id, week,
    })));
    expect(actions.slice(1).every((c) => c.sessionId === "plan-sess")).toBe(true);
    expect(screen.getByText(/2 of 6 weeks applied · failed: W3/)).toBeInTheDocument();
    expect(screen.queryByText(/Apply plan week/)).not.toBeInTheDocument();
    expect(coachBubbles()).toBe(oneBubble);
    expect(screen.getByText("Check-In Report").closest("button")).toBeEnabled();

    // Resume re-runs the loop for the remaining weeks (3..6); the last week's reply is the only new bubble.
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    await waitFor(() => expect(screen.getByText("Applied to TrainingPeaks")).toBeInTheDocument());
    expect(actions.slice(4).map((c) => (c.action as { week: number }).week)).toEqual([3, 4, 5, 6]);
    expect(screen.getByText("Resume applying plan to TrainingPeaks")).toBeInTheDocument();
    expect(screen.getByText(/TrainingPeaks updated: 6 weeks/)).toBeInTheDocument();
    expect(coachBubbles()).toBe(oneBubble + 1);
  });

  // Wednesday 2026-11-11 (local) -> next Monday 2026-11-16.
  const now = new Date(2026, 10, 11, 12);
  const summary = (active_date: string | null, active_start_date: string | null = null) => ({
    ...DEMO_ME_READY.summary!,
    active_goal: "Sub-3:20 Marathon",
    active_date,
    active_start_date,
  });

  it("builds the next block from its start date to the race", () => {
    const cfg = buildPlanAction(summary("2027-05-16", "2026-11-30"), now);
    expect(cfg.action).toEqual({ skill: "plan-builder", start_date: "2026-11-30", end_date: "2027-05-16", mode: "new" });
    expect(cfg.subtitle).toBe("Next block: Sub-3:20 Marathon · 30 Nov → 16 May (24 weeks)");
    expect(cfg.prompt).toBe("Build my training plan for Sub-3:20 Marathon from 2026-11-30 to 2027-05-16");
  });

  it("starts next Monday when the block already started or has no start date", () => {
    for (const start of ["2026-09-01", null]) {
      const cfg = buildPlanAction(summary("2027-02-07", start), now);
      expect(cfg.action).toMatchObject({ start_date: "2026-11-16", end_date: "2027-02-07" });
      expect(cfg.subtitle).toContain("16 Nov → 7 Feb (12 weeks)");
    }
  });

  it("asks for a goal in Profile without a future race, and the card opens the profile", () => {
    for (const s of [null, summary(null), summary("2026-11-11"), summary("2026-10-01")]) {
      const cfg = buildPlanAction(s, now);
      expect(cfg.action).toBeUndefined();
      expect(cfg.subtitle).toMatch(/goal race in your Profile/);
    }
    const onViewProfile = vi.fn();
    const onSendPrompt = vi.fn();
    render(
      <Dashboard
        me={{ ...DEMO_ME_READY, summary: summary(null) }}
        messages={[]}
        streaming={false}
        onSendPrompt={onSendPrompt}
        onViewProfile={onViewProfile}
        onOpenTrainingPeaks={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Build Plan"));
    expect(onViewProfile).toHaveBeenCalledTimes(1);
    expect(onSendPrompt).not.toHaveBeenCalled();
  });
});
