import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { ConnectTrainingPeaksDialog } from "../features/profile/ConnectTrainingPeaksDialog";
import { Dashboard } from "./Dashboard";
import { ProfilePanel } from "../features/profile/ProfilePanel";
import { TopBar } from "./TopBar";
import type { PlanApplying } from "./ChatFeed";
import {
  createNewSession,
  fetchMe,
  onSessionExpired,
  streamChat,
} from "../shared/api";
import type {
  AppliedTrainingPlan,
  ChatMessage,
  ConnectTpResponse,
  MeResponse,
  ProfileResponse,
  QuickAction,
} from "../shared/types";

const SESSION_IDLE_MS = 4 * 60 * 60 * 1000; // matches agent CONTEXT_WINDOW

export function App() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingBoot, setLoadingBoot] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [draft, setDraft] = useState("");
  const [sessionExpiredBanner, setSessionExpiredBanner] = useState(false);
  const lastActivityRef = useRef(0);

  const [profileDrawerOpen, setProfileDrawerOpen] = useState(false);
  const [profileDrawerMode, setProfileDrawerMode] = useState<"view" | "edit">(
    "view",
  );
  const [tpDialogOpen, setTpDialogOpen] = useState(false);
  const [appliedStagedIds, setAppliedStagedIds] = useState<ReadonlySet<string>>(new Set());
  const [applyingStagedId, setApplyingStagedId] = useState<string | null>(null);
  // Staged training plan, applied week by week (latest progress per plan, loop position, stopped plans).
  const [planApplied, setPlanApplied] = useState<Readonly<Record<string, AppliedTrainingPlan>>>({});
  const [planApplying, setPlanApplying] = useState<PlanApplying | null>(null);
  const [planFailedIds, setPlanFailedIds] = useState<ReadonlySet<string>>(new Set());
  // The apply loop awaits several turns from one closure, so it reads these through refs.
  const planAppliedRef = useRef<Record<string, AppliedTrainingPlan>>({});
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  useEffect(() => {
    onSessionExpired(() => {
      setSessionExpiredBanner(true);
      window.setTimeout(() => {
        window.location.reload();
      }, 1200);
    });
    return () => onSessionExpired(null);
  }, []);

  const loadInitialState = useCallback(async () => {
    setLoadingBoot(true);
    setBootError(null);
    try {
      const meRes = await fetchMe();
      setMe(meRes);
      setSessionId(null);
      setMessages([]);
      lastActivityRef.current = 0;
      if (import.meta.env.VITE_DEMO_MODE === "true") {
        const demoView = new URLSearchParams(window.location.search).get("view");
        if (demoView === "checkin" || demoView === "trend" || demoView === "audit" || demoView === "workout" || demoView === "plan") {
          const mod = await import("../demo/mockApi");
          const demoSess = await mod.demoFetchSession();
          setSessionId(demoSess.session_id);
          setMessages(demoSess.messages);
        } else if (demoView === "profile") {
          setProfileDrawerMode("view");
          setProfileDrawerOpen(true);
        }
      }
    } catch (err) {
      setBootError(
        err instanceof Error
          ? err.message
          : "Unable to load AI Running Coach right now.",
      );
    } finally {
      setLoadingBoot(false);
    }
  }, []);

  useEffect(() => {
    void loadInitialState();
  }, [loadInitialState]);

  const handleNewSession = async () => {
    if (streaming || planApplying) return;
    setDraft("");
    // Already on a fresh, empty session — nothing else to reset.
    if (messages.length === 0 && sessionId) return;
    setMessages([]);
    setSessionId(null);
    lastActivityRef.current = 0;
    setStreaming(true);
    try {
      const created = await createNewSession();
      setSessionId(created.session_id);
    } catch {
      // The next message creates the session instead.
    } finally {
      setStreaming(false);
    }
  };

  /**
   * Sends one turn and resolves `true` when its stream finished without an error.
   * `silent` (plan apply loop): no user bubble, and an assistant bubble only once reply text
   * (or an error) arrives, so intermediate weeks leave the feed untouched.
   */
  const handleSendPrompt = async (
    prompt: string,
    newConversation = false,
    action?: QuickAction,
    { silent = false }: { silent?: boolean } = {},
  ): Promise<boolean> => {
    if ((streaming && !silent) || !me) return false;
    const idle =
      lastActivityRef.current > 0 &&
      Date.now() - lastActivityRef.current > SESSION_IDLE_MS;
    // Applying staged changes / a staged plan must stay in the session that holds them.
    const isApply = action?.skill === "workout-creator";
    const isPlanApply = action?.skill === "plan-builder:apply";
    const startFresh =
      !isApply && !isPlanApply && (newConversation || idle) && messagesRef.current.length > 0;
    const targetSessionId = startFresh ? null : sessionIdRef.current;
    if (startFresh) {
      setSessionId(null);
    }
    const stamp = Date.now();
    const userMsgId = `u-${stamp}`;
    const assistantMsgId = `a-${stamp + 1}`;
    let failed = false;

    /** Updates the turn's assistant bubble; in silent mode it is created only when `create` is set. */
    const patchAssistant = (patch: (m: ChatMessage) => ChatMessage, create = false) => {
      setMessages((prev) => {
        if (prev.some((m) => m.id === assistantMsgId)) {
          return prev.map((m) => (m.id === assistantMsgId ? patch(m) : m));
        }
        if (!create) return prev;
        return [
          ...prev,
          patch({ id: assistantMsgId, role: "assistant", text: "", kind: "chat", streaming: true, tools: [] }),
        ];
      });
    };

    if (!silent) {
      setMessages((prev) => [
        ...(startFresh ? [] : prev),
        {
          id: userMsgId,
          role: "user",
          text: prompt,
          kind: "chat",
        },
        {
          id: assistantMsgId,
          role: "assistant",
          text: "",
          kind: "chat",
          streaming: true,
          thinking: true,
          tools: [],
        },
      ]);
    }
    setStreaming(true);

    try {
      await streamChat(
        {
          message: prompt,
          sessionId: targetSessionId,
          ...(action ? { action } : {}),
        },
        {
          onSession: (sid) => {
            if (sid) {
              sessionIdRef.current = sid;
              setSessionId(sid);
            }
          },
          onStatus: (phase) => {
            if (phase === "thinking") {
              patchAssistant((m) => ({ ...m, thinking: true }));
            }
          },
          onTool: (chip) => {
            patchAssistant((m) => {
              const existing = m.tools || [];
              const found = existing.some((t) => t.name === chip.name);
              const updatedTools = found
                ? existing.map((t) => (t.name === chip.name ? chip : t))
                : [...existing, chip];
              return { ...m, thinking: false, tools: updatedTools };
            });
          },
          onDelta: (deltaText) => {
            patchAssistant((m) => ({ ...m, thinking: false, text: m.text + deltaText }), true);
          },
          onReport: (report) => {
            patchAssistant((m) => ({ ...m, report, kind: report.kind }));
          },
          onStaged: (staged) => {
            patchAssistant((m) => ({ ...m, staged }));
          },
          onApplied: (applied) => {
            setAppliedStagedIds((prev) => new Set(prev).add(applied.staged_id));
          },
          onPlanStaged: (plan) => {
            patchAssistant((m) => ({ ...m, plan }), true);
          },
          onPlanApplied: (applied) => {
            planAppliedRef.current = { ...planAppliedRef.current, [applied.staged_id]: applied };
            setPlanApplied(planAppliedRef.current);
          },
          onMessage: ({ text, kind }) => {
            patchAssistant((m) => ({ ...m, thinking: false, text, kind }), true);
          },
          onError: (errMsg) => {
            failed = true;
            patchAssistant((m) => ({ ...m, thinking: false, streaming: false, error: errMsg }), true);
          },
          onDone: () => {
            lastActivityRef.current = Date.now();
            patchAssistant((m) => ({ ...m, thinking: false, streaming: false }));
          },
        },
      );

      // Refresh /api/me if onboarding or goal change might have occurred
      if (
        me.profile_state !== "ready" ||
        prompt.toLowerCase().includes("goal") ||
        prompt.toLowerCase().includes("profile")
      ) {
        const refreshed = await fetchMe();
        setMe(refreshed);
      }
    } catch (err) {
      failed = true;
      const errMsg =
        err instanceof Error ? err.message : "Failed to reach running coach.";
      patchAssistant((m) => ({ ...m, thinking: false, streaming: false, error: errMsg }), true);
    } finally {
      setStreaming(false);
      if (isApply) setApplyingStagedId(null);
    }
    return !failed;
  };

  const handleApplyStaged = (stagedId: string) => {
    if (streaming) return;
    setApplyingStagedId(stagedId);
    void handleSendPrompt("Update TrainingPeaks", false, {
      skill: "workout-creator",
      staged_id: stagedId,
    });
  };

  /**
   * "Apply to TrainingPeaks" / "Resume" on a staged plan: one visible user bubble, then one silent
   * `plan-builder:apply` turn per week not yet applied, in order. Stops on a stream error or a failed
   * week (the card then offers Resume, which re-runs this loop for the remaining weeks).
   */
  const handleApplyPlan = async (stagedId: string) => {
    if (streaming || planApplying) return;
    const plan = [...messagesRef.current].reverse().find((m) => m.plan?.staged_id === stagedId)?.plan;
    if (!plan) return;
    const resume = Boolean(planAppliedRef.current[stagedId] || planFailedIds.has(stagedId));
    const doneWeeks = new Set(planAppliedRef.current[stagedId]?.weeks_done ?? []);
    const remaining = plan.weeks.map((w) => w.week).filter((w) => !doneWeeks.has(w));
    if (remaining.length === 0) return;

    setPlanFailedIds((prev) => {
      const next = new Set(prev);
      next.delete(stagedId);
      return next;
    });
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        text: resume ? "Resume applying plan to TrainingPeaks" : "Apply plan to TrainingPeaks",
        kind: "chat",
      },
    ]);

    let stopped = false;
    for (const week of remaining) {
      setPlanApplying({ stagedId, week });
      const ok = await handleSendPrompt(
        `Apply plan week ${week}`,
        false,
        { skill: "plan-builder:apply", staged_id: stagedId, week },
        { silent: true },
      );
      const state = planAppliedRef.current[stagedId];
      if (!ok || state?.failed_weeks?.includes(week)) {
        stopped = true;
        break;
      }
      if (state?.done) break;
    }
    if (stopped) {
      setPlanFailedIds((prev) => new Set(prev).add(stagedId));
    }
    setPlanApplying(null);
  };

  const handleHome = () => {
    // "Home" = the Daily Coaching Hub at the top of the page; the conversation is kept.
    setProfileDrawerOpen(false);
    setTpDialogOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.getElementById("coaching-hub")?.focus({ preventScroll: true });
  };

  const handleTpConnected = async (res: ConnectTpResponse) => {
    const wasUnready = me?.profile_state !== "ready";
    const refreshed = await fetchMe();
    setMe(refreshed);
    if (wasUnready && res.profile_state === "needs_onboarding") {
      setTpDialogOpen(false);
    }
  };

  const handleProfileUpdated = (updated: ProfileResponse) => {
    setMe((prev) =>
      prev
        ? {
            ...prev,
            runner_id: updated.runner_id,
            profile_state: updated.profile_state,
            tp: updated.tp,
            summary: updated.summary ?? prev.summary,
            display_name: updated.summary?.full_name || prev.display_name,
          }
        : prev,
    );
  };

  // The plan apply loop spans several turns: keep the hub disabled between them too.
  const busy = streaming || planApplying !== null;

  if (loadingBoot) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-white text-slate-600">
        <Loader2 className="h-7 w-7 animate-spin text-orange-500 mb-3" />
        <p className="font-display text-base font-semibold text-slate-800">
          Loading AI Running Coach…
        </p>
      </div>
    );
  }

  if (bootError || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white p-6">
        <div className="max-w-md rounded-3xl border border-rose-200 bg-rose-50/60 p-6 text-center space-y-3">
          <AlertCircle className="mx-auto h-8 w-8 text-rose-600" />
          <h1 className="font-display text-lg font-bold text-slate-900">
            Could not load your coaching workspace
          </h1>
          <p className="text-sm text-slate-600">{bootError}</p>
          <button
            type="button"
            onClick={() => void loadInitialState()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-4 py-2 text-sm font-semibold text-white shadow-sunset cursor-pointer"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white text-slate-900">
      {sessionExpiredBanner && (
        <div className="bg-sunset px-4 py-2 text-center text-sm font-semibold text-white">
          Your sign-in session expired — refreshing authentication…
        </div>
      )}

      <TopBar
        me={me}
        newSessionDisabled={busy}
        onHome={handleHome}
        onNewSession={handleNewSession}
        onViewProfile={() => {
          setProfileDrawerMode("view");
          setProfileDrawerOpen(true);
        }}
        onEditProfile={() => {
          setProfileDrawerMode("edit");
          setProfileDrawerOpen(true);
        }}
        onOpenTrainingPeaks={() => setTpDialogOpen(true)}
      />

      <Dashboard
        me={me}
        messages={messages}
        streaming={busy}
        onSendPrompt={handleSendPrompt}
        draft={draft}
        onDraftChange={setDraft}
        appliedStagedIds={appliedStagedIds}
        applyingStagedId={applyingStagedId}
        onApplyStaged={handleApplyStaged}
        planApplied={planApplied}
        planApplying={planApplying}
        planFailedIds={planFailedIds}
        onApplyPlan={(stagedId) => void handleApplyPlan(stagedId)}
        onViewProfile={() => {
          setProfileDrawerMode("view");
          setProfileDrawerOpen(true);
        }}
        onOpenTrainingPeaks={() => setTpDialogOpen(true)}
      />

      <ProfilePanel
        open={profileDrawerOpen}
        initialMode={profileDrawerMode}
        email={me.email}
        initials={me.initials}
        onClose={() => setProfileDrawerOpen(false)}
        onOpenTrainingPeaks={() => {
          setProfileDrawerOpen(false);
          setTpDialogOpen(true);
        }}
        onProfileUpdated={handleProfileUpdated}
      />

      <ConnectTrainingPeaksDialog
        open={tpDialogOpen}
        tpStatus={me.tp}
        onClose={() => setTpDialogOpen(false)}
        onConnected={handleTpConnected}
      />
    </div>
  );
}
