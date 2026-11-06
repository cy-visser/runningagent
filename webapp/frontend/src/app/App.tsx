import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { ConnectTrainingPeaksDialog } from "../features/profile/ConnectTrainingPeaksDialog";
import { Dashboard } from "./Dashboard";
import { ProfilePanel } from "../features/profile/ProfilePanel";
import { TopBar } from "./TopBar";
import {
  createNewSession,
  fetchMe,
  onSessionExpired,
  streamChat,
} from "../shared/api";
import type {
  ChatMessage,
  ConnectTpResponse,
  MeResponse,
  ProfileResponse,
} from "../shared/types";

const SESSION_IDLE_MS = 4 * 60 * 60 * 1000; // matches agent CONTEXT_WINDOW

export function App() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingBoot, setLoadingBoot] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [sessionExpiredBanner, setSessionExpiredBanner] = useState(false);
  const lastActivityRef = useRef(0);

  const [profileDrawerOpen, setProfileDrawerOpen] = useState(false);
  const [profileDrawerMode, setProfileDrawerMode] = useState<"view" | "edit">(
    "view",
  );
  const [tpDialogOpen, setTpDialogOpen] = useState(false);

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
        if (demoView === "checkin" || demoView === "trend") {
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
    if (streaming) return;
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

  const handleSendPrompt = async (prompt: string, newConversation = false) => {
    if (streaming || !me) return;
    const idle =
      lastActivityRef.current > 0 &&
      Date.now() - lastActivityRef.current > SESSION_IDLE_MS;
    const startFresh = (newConversation || idle) && messages.length > 0;
    const targetSessionId = startFresh ? null : sessionId;
    if (startFresh) {
      setSessionId(null);
    }
    const userMsgId = `u-${Date.now()}`;
    const assistantMsgId = `a-${Date.now() + 1}`;

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
    setStreaming(true);

    try {
      await streamChat(
        { message: prompt, sessionId: targetSessionId },
        {
          onSession: (sid) => {
            if (sid) setSessionId(sid);
          },
          onStatus: (phase) => {
            if (phase === "thinking") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId ? { ...m, thinking: true } : m,
                ),
              );
            }
          },
          onTool: (chip) => {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== assistantMsgId) return m;
                const existing = m.tools || [];
                const found = existing.some((t) => t.name === chip.name);
                const updatedTools = found
                  ? existing.map((t) => (t.name === chip.name ? chip : t))
                  : [...existing, chip];
                return { ...m, thinking: false, tools: updatedTools };
              }),
            );
          },
          onDelta: (deltaText) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, thinking: false, text: m.text + deltaText }
                  : m,
              ),
            );
          },
          onReport: (report) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, report, kind: report.kind }
                  : m,
              ),
            );
          },
          onMessage: ({ text, kind }) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, thinking: false, text, kind }
                  : m,
              ),
            );
          },
          onError: (errMsg) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, thinking: false, streaming: false, error: errMsg }
                  : m,
              ),
            );
          },
          onDone: () => {
            lastActivityRef.current = Date.now();
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, thinking: false, streaming: false }
                  : m,
              ),
            );
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
      const errMsg =
        err instanceof Error ? err.message : "Failed to reach running coach.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, thinking: false, streaming: false, error: errMsg }
            : m,
        ),
      );
    } finally {
      setStreaming(false);
    }
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

  if (loadingBoot) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-white text-slate-600">
        <Loader2 className="h-7 w-7 animate-spin text-orange-500 mb-3" />
        <p className="font-display text-sm font-semibold text-slate-800">
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
          <h1 className="font-display text-base font-bold text-slate-900">
            Could not load your coaching workspace
          </h1>
          <p className="text-xs text-slate-600">{bootError}</p>
          <button
            type="button"
            onClick={() => void loadInitialState()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-sunset px-4 py-2 text-xs font-semibold text-white shadow-sunset cursor-pointer"
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
        <div className="bg-sunset px-4 py-2 text-center text-xs font-semibold text-white">
          Your sign-in session expired — refreshing authentication…
        </div>
      )}

      <TopBar
        me={me}
        hasMessages={messages.length > 0}
        onHome={() => window.scrollTo({ top: 0, behavior: "smooth" })}
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
        streaming={streaming}
        onSendPrompt={handleSendPrompt}
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
