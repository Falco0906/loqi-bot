"use client";

import { useEffect, useRef, useState } from "react";

import { createSession, getGmailStatus, getSession, sendMessage } from "../../lib/api";
import type { LoqiMessage, LoqiSessionSummary } from "../../lib/types";

const ACTIVE_SESSION_STORAGE_KEY = "loqi_active_session_token";
const SESSION_INDEX_STORAGE_KEY = "loqi_session_index";
const SIDEBAR_OPEN_STORAGE_KEY = "loqi_sidebar_open";

type StoredSession = {
  token: string;
  title: string;
  updatedAt: string;
};

function formatMessageTime(value?: string) {
  if (!value) {
    return "Just now";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Just now";
  }

  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function deriveSessionTitle(messages: LoqiMessage[], fallback = "New chat") {
  const firstUserMessage = messages.find((message) => message.role === "user" && message.text.trim());
  if (!firstUserMessage) {
    return fallback;
  }

  const normalized = firstUserMessage.text.replace(/\s+/g, " ").trim();
  return normalized.length > 34 ? `${normalized.slice(0, 34)}...` : normalized;
}

function readStoredSessions() {
  if (typeof window === "undefined") {
    return [] as StoredSession[];
  }

  try {
    const raw = window.localStorage.getItem(SESSION_INDEX_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw) as StoredSession[];
    return Array.isArray(parsed)
      ? parsed.filter((item) => typeof item?.token === "string" && item.token.trim())
      : [];
  } catch {
    return [];
  }
}

function writeStoredSessions(sessions: StoredSession[]) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(SESSION_INDEX_STORAGE_KEY, JSON.stringify(sessions));
  } catch {
    return;
  }
}

function upsertStoredSession(nextSession: StoredSession) {
  const sessions = readStoredSessions().filter((item) => item.token !== nextSession.token);
  const updated = [nextSession, ...sessions].slice(0, 50);
  writeStoredSessions(updated);
  return updated;
}

function readStorageItem(key: string) {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorageItem(key: string, value: string) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function MessageBlock({ message }: { message: LoqiMessage }) {
  const isUser = message.role === "user";
  const leads = Array.isArray(message.data?.leads)
    ? (message.data?.leads as Array<Record<string, string>>)
    : [];
  const draft = typeof message.data?.draft === "string" ? message.data.draft : null;
  const actionUrl = typeof message.data?.url === "string" ? message.data.url : null;
  const timestamp = formatMessageTime(message.created_at);

  return (
    <div className={`flex gap-2 sm:gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser ? (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#2a3346] text-xs font-semibold text-[#aebee3] sm:mt-1 sm:h-8 sm:w-8 sm:text-sm">
          L
        </div>
      ) : null}

      <div className={`flex max-w-[85vw] flex-col sm:max-w-[min(82%,46rem)] ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`w-full rounded-2xl px-4 py-3 sm:rounded-[1.35rem] sm:px-5 sm:py-4 ${
            isUser
              ? "bg-[linear-gradient(135deg,#5e63ee_0%,#6e6bf3_100%)] text-white shadow-[0_8px_20px_rgba(95,100,238,0.18)]"
              : "bg-[#232834] text-[#edf1ff]"
          }`}
        >
          <p className="whitespace-pre-wrap text-[14px] leading-6 sm:text-[15px] sm:leading-7">{message.text}</p>

          {leads.length > 0 ? (
            <div className="mt-3 grid gap-2 sm:mt-4 sm:grid-cols-1 lg:grid-cols-2">
              {leads.map((lead, index) => (
                <div
                  key={`${lead.name}-${index}`}
                  className="rounded-xl border border-white/8 bg-black/10 p-3 sm:p-3.5"
                >
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[#8e98b3] sm:text-[10px] sm:tracking-[0.24em]">
                    Lead {index + 1}
                  </div>
                  <div className="mt-1.5 text-sm font-semibold text-white sm:mt-2 sm:text-sm">
                    {lead.name || "Unknown"}
                  </div>
                  <div className="mt-1 text-xs text-[#bec7dc] sm:text-sm">
                    {[lead.title, lead.company].filter(Boolean).join(" @ ")}
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {draft ? (
            <div className="mt-3 rounded-xl border border-emerald-300/10 bg-emerald-400/5 p-3 sm:mt-4 sm:rounded-[0.95rem] sm:p-3.5">
              <div className="text-[10px] uppercase tracking-[0.2em] text-emerald-200/75 sm:text-[10px] sm:tracking-[0.24em]">
                Draft Preview
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-5 text-[#f3fff9] sm:mt-2 sm:text-sm sm:leading-6">{draft}</p>
            </div>
          ) : null}

          {actionUrl ? (
            <div className="mt-3 sm:mt-4">
              <a
                href={actionUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white no-underline transition hover:bg-white/15 sm:px-3.5 sm:py-2 sm:text-xs"
              >
                Connect Gmail
              </a>
            </div>
          ) : null}
        </div>

        <div
          className={`mt-1 px-0.5 text-[11px] sm:mt-1.5 sm:px-1 ${
            isUser ? "text-right text-[#969fd3]" : "text-left text-[#67728f]"
          }`}
        >
          {timestamp}
        </div>
      </div>
    </div>
  );
}

export function LoqiApp() {
  const [session, setSession] = useState<LoqiSessionSummary | null>(null);
  const [composer, setComposer] = useState("");
  const [messages, setMessages] = useState<LoqiMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [gmailConnected, setGmailConnected] = useState(false);
  const [gmailUrl, setGmailUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [storedSessions, setStoredSessions] = useState<StoredSession[]>([]);
  const [isMobile, setIsMobile] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const checkMobile = () => {
      setIsMobile(window.innerWidth < 640);
      const storedSidebarOpen = readStorageItem(SIDEBAR_OPEN_STORAGE_KEY);
      if (storedSidebarOpen === "1") {
        setSidebarOpen(true);
      }
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);

    setStoredSessions(readStoredSessions());

    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    writeStorageItem(SIDEBAR_OPEN_STORAGE_KEY, sidebarOpen ? "1" : "0");
  }, [sidebarOpen]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function loadSession(sessionToken: string) {
    setLoading(true);
    setError(null);

    try {
      const [summary, gmail] = await Promise.all([
        getSession(sessionToken),
        getGmailStatus(sessionToken),
      ]);

      setSession(summary);
      setMessages(summary.messages);
      setGmailConnected(gmail.gmail_connected);
      setGmailUrl(gmail.connect_url);
      writeStorageItem(ACTIVE_SESSION_STORAGE_KEY, sessionToken);

      const updatedSessions = upsertStoredSession({
        token: sessionToken,
        title: deriveSessionTitle(summary.messages),
        updatedAt: new Date().toISOString(),
      });
      setStoredSessions(updatedSessions);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load chat.");
    } finally {
      setLoading(false);
    }
  }

  async function createAndLoadSession() {
    setLoading(true);
    setError(null);

    try {
      const created = await createSession("Loqi Operator");
      const sessionToken = created.session_token;

      const updatedSessions = upsertStoredSession({
        token: sessionToken,
        title: "New chat",
        updatedAt: new Date().toISOString(),
      });
      setStoredSessions(updatedSessions);

      await loadSession(sessionToken);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start a new chat.");
      setLoading(false);
    }
  }

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    async function bootstrap() {
      const activeSessionToken = readStorageItem(ACTIVE_SESSION_STORAGE_KEY);
      const indexedSessions = readStoredSessions();
      setStoredSessions(indexedSessions);

      if (activeSessionToken) {
        await loadSession(activeSessionToken);
        return;
      }

      if (indexedSessions[0]?.token) {
        await loadSession(indexedSessions[0].token);
        return;
      }

      await createAndLoadSession();
    }

    void bootstrap();

    const listener = () => {
      const token = readStorageItem(ACTIVE_SESSION_STORAGE_KEY);
      if (!token) {
        return;
      }

      void getGmailStatus(token).then((gmail) => {
        setGmailConnected(gmail.gmail_connected);
        setGmailUrl(gmail.connect_url);
      });
    };

    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, []);

  async function handleNewChat() {
    if (sending) {
      return;
    }

    setSidebarOpen(false);
    setComposer("");
    await createAndLoadSession();
  }

  async function handleSelectChat(sessionToken: string) {
    if (sending || session?.session_token === sessionToken) {
      return;
    }

    setSidebarOpen(false);
    setComposer("");
    await loadSession(sessionToken);
  }

  async function handleSend() {
    if (!session || !composer.trim() || sending) {
      return;
    }

    const pendingUserMessage: LoqiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      type: "text",
      text: composer.trim(),
    };

    setMessages((current) => [...current, pendingUserMessage]);
    setComposer("");
    setSending(true);

    try {
      setError(null);
      const response = await sendMessage(session.session_token, pendingUserMessage.text);
      const mergedMessages = [...messages, pendingUserMessage, ...response.messages];
      setMessages((current) => [...current, ...response.messages]);

      const refreshed = await getSession(session.session_token);
      setSession(refreshed);
      setGmailConnected(refreshed.gmail_connected);

      const updatedSessions = upsertStoredSession({
        token: session.session_token,
        title: deriveSessionTitle(mergedMessages),
        updatedAt: new Date().toISOString(),
      });
      setStoredSessions(updatedSessions);
    } catch (caught) {
      setMessages((current) => current.filter((item) => item.id !== pendingUserMessage.id));
      setComposer(pendingUserMessage.text);
      setError(caught instanceof Error ? caught.message : "Unable to send message.");
    } finally {
      setSending(false);
    }
  }

  if (loading && !session) {
    return (
      <main className="flex h-screen items-center justify-center bg-[#141824] px-4 sm:grid sm:place-items-center">
        <div className="rounded-2xl bg-white/[0.03] px-5 py-4 text-sm text-slate-200 sm:px-6 sm:py-4 sm:text-base">
          Loading Loqi workspace...
        </div>
      </main>
    );
  }

  return (
    <>
      {sidebarOpen && isMobile && (
        <div
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm sm:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={`${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        } fixed inset-y-0 left-0 z-40 w-[280px] -translate-x-full transform flex-col bg-[#12151d]/98 shadow-[20px_0_80px_rgba(0,0,0,0.38)] transition-transform duration-200 ease-out sm:relative sm:z-auto sm:flex sm:w-[260px] sm:min-w-[260px] sm:translate-x-0`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between px-4 pb-3 pt-4">
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#1f2431] text-[#dbe3fb] transition hover:bg-[#262c3a] sm:hidden"
              aria-label="Close sidebar"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <div className="hidden sm:block" />
            <button
              type="button"
              onClick={() => void handleNewChat()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#1f2431] text-[#dbe3fb] transition hover:bg-[#262c3a]"
              aria-label="New chat"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 5v14" />
                <path d="M5 12h14" />
              </svg>
            </button>
          </div>

          <div className="px-4 pt-2">
            <button
              type="button"
              onClick={() => gmailUrl && window.open(gmailUrl, "_blank", "width=580,height=720")}
              className="flex w-full items-center justify-between rounded-xl bg-[#1a1e29] px-4 py-3 text-left text-sm text-[#dbe3fb] shadow-[0_10px_28px_rgba(0,0,0,0.18)] transition hover:bg-[#232837]"
            >
              <span>Connect Gmail</span>
              <span
                className={`rounded-full px-2 py-1 text-[11px] ${
                  gmailConnected ? "bg-emerald-400/15 text-emerald-200" : "bg-white/5 text-[#9ca8c7]"
                }`}
              >
                {gmailConnected ? "On" : "Off"}
              </span>
            </button>
          </div>

          <div className="px-4 pt-5 text-xs font-semibold uppercase tracking-[0.18em] text-[#6e7896]">
            Recents
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-3">
            <div className="space-y-1.5">
              {storedSessions.map((item) => {
                const isActive = item.token === session?.session_token;

                return (
                  <button
                    key={item.token}
                    type="button"
                    onClick={() => void handleSelectChat(item.token)}
                    className={`flex w-full flex-col rounded-xl px-3 py-3 text-left transition ${
                      isActive
                        ? "bg-[#272c38] text-white shadow-[0_10px_28px_rgba(0,0,0,0.16)]"
                        : "text-[#d4dcf5] hover:bg-[#1b1f2a]"
                    }`}
                  >
                    <span className="truncate text-sm font-medium">{item.title}</span>
                    <span className="mt-1 text-xs text-[#7782a0]">
                      {formatMessageTime(item.updatedAt)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </aside>

      <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="absolute left-4 top-4 z-20 sm:left-7 sm:top-7">
          <button
            type="button"
            onClick={() => setSidebarOpen((current) => !current)}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#1f2431] text-[#dbe3fb] shadow-lg transition hover:bg-[#262c3a] sm:static sm:hidden sm:h-auto sm:w-auto sm:bg-transparent sm:text-[1.05rem] sm:font-semibold sm:tracking-[-0.07em] sm:text-white sm:shadow-none sm:hover:opacity-80"
            aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            {isMobile ? (
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            ) : (
              "loqi"
            )}
          </button>
          {!isMobile && (
            <span className="ml-2 text-[1.05rem] font-semibold tracking-[-0.07em] text-white">
              loqi
            </span>
          )}
        </div>

        {error ? (
          <div className="mx-4 mb-2 mt-16 rounded-xl border border-rose-400/10 bg-rose-400/6 px-4 py-2 text-sm text-rose-100 sm:mx-5">
            {error}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-3 pt-16 sm:px-5 sm:pt-16">
          <div className="mx-auto flex w-full max-w-[980px] flex-col gap-5 sm:gap-6">
            {messages.length === 0 ? (
              <div className="flex h-full min-h-[280px] items-center justify-center sm:min-h-[320px]">
                <div className="max-w-md px-4 text-center sm:max-w-xl sm:px-0">
                  <div className="text-[1.75rem] font-semibold tracking-[-0.04em] text-white sm:text-[2rem] sm:tracking-[-0.05em]">
                    Run your outbound from chat
                  </div>
                  <p className="mt-2.5 text-[14px] leading-6 text-[#98a2bf] sm:mt-3 sm:text-base sm:leading-7">
                    Tell Loqi what you sell and who you want to reach. It will find leads,
                    draft outreach, and wait for your approval.
                  </p>
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <MessageBlock key={message.id} message={message} />
              ))
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="px-3 pb-[env(safe-area-inset-bottom)] pt-2 sm:px-5 sm:pb-5">
          <div className="mx-auto max-w-[980px] rounded-2xl bg-[#232834] p-2 shadow-[0_12px_48px_rgba(4,7,18,0.28)] sm:rounded-[1.25rem] sm:p-2.5">
            <textarea
              ref={textareaRef}
              value={composer}
              onChange={(event) => setComposer(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void handleSend();
                }
              }}
              placeholder="Type a message..."
              rows={1}
              className="min-h-10 w-full resize-none border-0 bg-transparent px-3 py-2 text-[15px] leading-6 text-[#edf1ff] outline-none placeholder:text-[#8994b6] sm:min-h-11 sm:px-2 sm:py-1.5 sm:text-[14px] sm:leading-6"
              style={{ height: "auto" }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
              }}
            />
            <div className="flex items-center justify-end border-t border-white/[0.06] px-2 pt-1.5 sm:pt-2">
              <button
                type="button"
                onClick={() => void handleSend()}
                disabled={sending || !composer.trim()}
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#5f64ee_0%,#6f6bf3_100%)] text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40 sm:h-11 sm:w-11 sm:rounded-2xl"
                aria-label="Send message"
              >
                {sending ? (
                  <span className="text-[11px] font-semibold">...</span>
                ) : (
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h11" />
                    <path d="M12 5l7 7-7 7" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}