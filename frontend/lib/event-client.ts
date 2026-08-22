"use client";

/**
 * PR-3D — authenticated SSE event client (singleton).
 *
 * Transport: fetch-based SSE (ReadableStream) so the Authorization header
 * carries the session token — EventSource cannot set headers and query-string
 * tokens leak into access logs.
 *
 * Contract:
 *   - ONE logical connection per authenticated browser session.
 *   - connect() after auth; stopEventStream() on logout.
 *   - Bounded reconnect backoff (1s → 30s), reset on successful open;
 *     immediate reconnect when the tab becomes visible again.
 *   - Handlers receive parsed events and act ONLY as cache-invalidation /
 *     revalidation triggers. REST remains authoritative — never paste an
 *     event payload into page state.
 */

export type ServerEvent = {
  type: string;
  job_id?: string;
  status?: string;
  progress?: number;
  user?: string;
  data?: Record<string, unknown>;
};

type Handler = (event: ServerEvent) => void;

const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

const handlers = new Set<Handler>();
let controller: AbortController | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let attempt = 0;
let running = false;
let currentToken: string | null = null;

const MAX_BACKOFF_MS = 30_000;

function debug(msg: string): void {
  try {
    if (localStorage.getItem("loqi_debug_cache") === "1") {
      console.debug(`[events] ${msg}`);
    }
  } catch { /* noop */ }
}

function getToken(): string | null {
  try {
    return localStorage.getItem("loqi_active_session_token");
  } catch {
    return null;
  }
}

/** Register a server-event handler. Returns an unsubscribe function. */
export function onServerEvent(handler: Handler): () => void {
  handlers.add(handler);
  return () => handlers.delete(handler);
}

/**
 * Start the stream for the current session. Idempotent: calling twice with
 * the same token is a no-op (protects against React Strict Mode double
 * effects). A different token (user switch) restarts the connection.
 */
export function startEventStream(): void {
  const token = getToken();
  if (!token) return;
  if (running && currentToken === token) return;
  if (running) stopEventStream();
  running = true;
  currentToken = token;
  void connectLoop();
}

/** Close the stream and cancel any pending reconnect (logout / unmount). */
export function stopEventStream(): void {
  running = false;
  currentToken = null;
  attempt = 0;
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (controller) {
    controller.abort();
    controller = null;
  }
}

async function connectLoop(): Promise<void> {
  while (running) {
    const token = getToken();
    if (!token) { running = false; return; }

    controller = new AbortController();
    const opened = await streamOnce(token);
    if (!running) return;

    if (opened) {
      attempt = 0;
      // Stream ended normally (server closed / revocation). Reconnect after
      // a short delay unless stopped or token changed.
      if (getToken() !== token) { running = false; return; }
      await sleep(1000);
      continue;
    }

    // Connection failed before opening → bounded exponential backoff.
    attempt += 1;
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(attempt, 5));
    debug(`reconnect in ${delay}ms (attempt ${attempt})`);
    await sleep(delay);
  }
}

async function streamOnce(token: string): Promise<boolean> {
  let opened = false;
  try {
    const res = await fetch(`${API_BASE}/api/events/stream`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
      signal: controller!.signal,
      cache: "no-store",
    });
    if (!res.ok || !res.body) {
      // 401/403/503 etc. — treat as failed open; backoff applies.
      return false;
    }
    opened = true;
    debug("stream opened");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const dataLine = chunk.split("\n").find(l => l.startsWith("data:"));
        if (!dataLine) continue; // heartbeats ("comment" lines) are ignored
        try {
          const event = JSON.parse(dataLine.slice(5).trim()) as ServerEvent;
          if (event && typeof event.type === "string") {
            dispatch(event);
          }
        } catch { /* malformed frame — ignore */ }
      }
    }
  } catch (error) {
    if ((error as Error)?.name === "AbortError") return opened || false;
    debug(`stream error ${JSON.stringify((error as any)?.message ?? "").slice(0, 80)}`);
  }
  return opened;
}

function dispatch(event: ServerEvent): void {
  debug(`event ${event.type}`);
  for (const handler of [...handlers]) {
    try {
      handler(event);
    } catch (e) {
      debug("handler error");
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => {
    reconnectTimer = setTimeout(() => { reconnectTimer = null; resolve(); }, ms);
  });
}
