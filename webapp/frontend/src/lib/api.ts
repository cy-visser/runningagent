import type {
  ChatStreamHandlers,
  ConnectTpResponse,
  MeResponse,
  MessageKind,
  ProfileResponse,
  ProfileUpdatePayload,
  ReportEnvelope,
  SessionResponse,
  ToolChip,
} from "../types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type SessionExpiredListener = () => void;

let sessionExpiredListener: SessionExpiredListener | null = null;

export function onSessionExpired(listener: SessionExpiredListener | null): void {
  sessionExpiredListener = listener;
}

function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

function buildHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    "X-Requested-With": "XMLHttpRequest",
    ...extra,
  };
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    sessionExpiredListener?.();
    throw new ApiError(401, "Your sign-in session expired. Refreshing sign-in…");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data?.detail) && data.detail.length > 0) {
        const first = data.detail[0] as { msg?: string };
        if (first?.msg) detail = first.msg;
      }
    } catch {
      // Non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export async function fetchMe(): Promise<MeResponse> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoFetchMe();
  }
  const res = await fetch("/api/me", {
    method: "GET",
    credentials: "same-origin",
    headers: buildHeaders(),
  });
  return handleResponse<MeResponse>(res);
}

export async function fetchProfile(): Promise<ProfileResponse> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoFetchProfile();
  }
  const res = await fetch("/api/profile", {
    method: "GET",
    credentials: "same-origin",
    headers: buildHeaders(),
  });
  return handleResponse<ProfileResponse>(res);
}

export async function updateProfile(
  payload: ProfileUpdatePayload,
): Promise<ProfileResponse> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoUpdateProfile(payload);
  }
  const res = await fetch("/api/profile", {
    method: "PUT",
    credentials: "same-origin",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return handleResponse<ProfileResponse>(res);
}

export async function connectTrainingPeaks(
  cookie: string,
): Promise<ConnectTpResponse> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoConnectTrainingPeaks(cookie);
  }
  const res = await fetch("/api/trainingpeaks/connect", {
    method: "POST",
    credentials: "same-origin",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ cookie }),
  });
  return handleResponse<ConnectTpResponse>(res);
}

export async function createNewSession(): Promise<SessionResponse> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoCreateNewSession();
  }
  const res = await fetch("/api/session/new", {
    method: "POST",
    credentials: "same-origin",
    headers: buildHeaders(),
  });
  return handleResponse<SessionResponse>(res);
}

export function parseSseFrame(
  rawFrame: string,
): { event: string; data: unknown } | null {
  const lines = rawFrame.split(/\r?\n/);
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }
  const rawJson = dataLines.join("\n");
  try {
    return { event: eventName, data: JSON.parse(rawJson) };
  } catch {
    return null;
  }
}

export async function streamChat(
  params: { message: string; sessionId?: string | null; signal?: AbortSignal },
  handlers: ChatStreamHandlers,
): Promise<void> {
  if (isDemoMode()) {
    const mod = await import("../demo/mockApi");
    return mod.demoStreamChat(params, handlers);
  }

  const res = await fetch("/api/chat", {
    method: "POST",
    credentials: "same-origin",
    signal: params.signal,
    headers: buildHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify({
      message: params.message,
      session_id: params.sessionId ?? null,
    }),
  });

  if (res.status === 401) {
    sessionExpiredListener?.();
    throw new ApiError(401, "Your sign-in session expired. Refreshing sign-in…");
  }
  if (!res.ok || !res.body) {
    await handleResponse(res);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawFrame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseFrame(rawFrame);
      if (parsed) {
        dispatchSseEvent(parsed.event, parsed.data, handlers);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseFrame(buffer);
    if (parsed) {
      dispatchSseEvent(parsed.event, parsed.data, handlers);
    }
  }
}

function dispatchSseEvent(
  event: string,
  data: unknown,
  handlers: ChatStreamHandlers,
): void {
  if (!data || typeof data !== "object") return;
  const obj = data as Record<string, unknown>;

  switch (event) {
    case "session":
      if (typeof obj.session_id === "string") {
        handlers.onSession?.(obj.session_id);
      }
      break;
    case "status":
      if (typeof obj.phase === "string") {
        handlers.onStatus?.(obj.phase);
      }
      break;
    case "tool":
      if (
        typeof obj.name === "string" &&
        typeof obj.label === "string" &&
        (obj.state === "start" || obj.state === "done")
      ) {
        handlers.onTool?.(obj as unknown as ToolChip);
      }
      break;
    case "delta":
      if (typeof obj.text === "string") {
        handlers.onDelta?.(obj.text);
      }
      break;
    case "report":
      if (
        (obj.kind === "checkin" || obj.kind === "trend") &&
        obj.data &&
        typeof obj.data === "object"
      ) {
        handlers.onReport?.(obj as unknown as ReportEnvelope);
      }
      break;
    case "message":
      if (typeof obj.text === "string") {
        handlers.onMessage?.({
          text: obj.text,
          kind: (obj.kind as MessageKind) || "chat",
        });
      }
      break;
    case "error":
      if (typeof obj.message === "string") {
        handlers.onError?.(obj.message);
      }
      break;
    case "done":
      handlers.onDone?.(typeof obj.session_id === "string" ? obj.session_id : "");
      break;
    default:
      break;
  }
}
