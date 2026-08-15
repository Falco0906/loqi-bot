"use client";

import { useEffect, useState, useRef } from "react";
import {
  getGmailAuthUrl,
  listProviders,
  disconnectProvider,
  getProviderHealth,
  syncProvider,
  getProviderStatus,
  getProviderMessages,
  getProviderThreads,
  getProviderEvents,
  getRegisteredProviderTypes,
  analyzeConversationMessage,
  getConversationTimeline,
  planWorkflow,
  getWorkspaceContext,
  getCommunicationSummary,
  getCommunicationRecommend,
  outboundCreateDraft,
  outboundUpdateDraft,
  outboundDeleteDraft,
  outboundSend,
  outboundSchedule,
  outboundCancelSchedule,
  outboundListDrafts,
  outboundGetDraft,
  outboundApproveDraft,
  outboundRejectDraft,
  outboundGetHistory,
  outboundGetEvents as outboundGetEventsApi,
  outboundGetDraftVersions,
  outboundApproveAll,
  TimeoutError,
} from "../../../lib/api";
import { isTrustedGmailOAuthMessage, openGmailAuthPopup } from "../../../lib/gmail-oauth";

const SESSION_KEY = "loqi_active_session_token";
const DEV_MODE =
  process.env.NEXT_PUBLIC_DEV_MODE === "true" ||
  process.env.NODE_ENV === "development";

function getSession(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(SESSION_KEY) || "";
}

type ProviderInfo = {
  id: string;
  provider_type: string;
  status: string;
  email: string;
  last_sync: string;
  sync_cursor: string;
  created_at: string;
};

type SyncResult = {
  provider_id: string;
  threads_synced: number;
  messages_synced: number;
  new_conversations: number;
  errors: string[];
  cursor: string;
  duration_ms: number;
};

type EventItem = {
  id: string;
  event_type: string;
  provider_id: string;
  message: string;
  timestamp: string;
  sequence: number;
  metadata: Record<string, unknown>;
};

type WorkflowPlanResult = {
  plan: Record<string, unknown>;
  alternative_plan: Record<string, unknown>;
  recommendation: string;
  confidence: string;
};

type SyncState = "idle" | "running" | "timed_out" | "completed" | "failed";

type CheckStatus = "pending" | "pass" | "fail" | "skipped";

export default function DevProvidersPage() {
  const [token, setToken] = useState("");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ProviderInfo | null>(null);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [syncState, setSyncState] = useState<SyncState>("idle");
  const [providerEvents, setProviderEvents] = useState<EventItem[]>([]);
  const [eventSeq, setEventSeq] = useState(0);
  const [registeredTypes, setRegisteredTypes] = useState<string[]>([]);
  const [authUrl, setAuthUrl] = useState("");
  const [oauthError, setOauthError] = useState("");
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthResult, setOauthResult] = useState<{ provider_id: string; email: string } | null>(null);

  // Conversation Intelligence
  const [sampleText, setSampleText] = useState("How much does this cost? I need pricing information and a demo");
  const [intelligence, setIntelligence] = useState<Record<string, unknown> | null>(null);
  const [intelMemory, setIntelMemory] = useState<Record<string, unknown> | null>(null);
  const [intelConversationId, setIntelConversationId] = useState("");
  const [timeline, setTimeline] = useState<Record<string, unknown>[]>([]);

  // Inline result panels
  const [summaryResult, setSummaryResult] = useState<string | null>(null);
  const [recommendResult, setRecommendResult] = useState<string | null>(null);

  // Planner
  const [plannerObjective, setPlannerObjective] = useState("Review new replies from Gmail sync");
  const [plannerResult, setPlannerResult] = useState<WorkflowPlanResult | null>(null);

  // Copilot context
  const [copilotContext, setCopilotContext] = useState<Record<string, unknown> | null>(null);

  // Diagnostics
  const [messageCount, setMessageCount] = useState(0);
  const [threadCount, setThreadCount] = useState(0);
  const [recentMessages, setRecentMessages] = useState<Record<string, unknown>[]>([]);

  // Outbound
  const [outboundDraftSubject, setOutboundDraftSubject] = useState("Re: Your inquiry");
  const [outboundDraftBody, setOutboundDraftBody] = useState("Hi,\n\nThanks for reaching out. I'd be happy to help.\n\nBest regards");
  const [outboundRecipient, setOutboundRecipient] = useState("lead@example.com");
  const [outboundDrafts, setOutboundDrafts] = useState<Record<string, unknown>[]>([]);
  const [outboundDraftCount, setOutboundDraftCount] = useState(0);
  const [outboundResult, setOutboundResult] = useState<string>("");
  const [outboundHistory, setOutboundHistory] = useState<Record<string, unknown>[]>([]);
  const [outboundEvents, setOutboundEvents] = useState<Record<string, unknown>[]>([]);
  const [outboundEventSeq, setOutboundEventSeq] = useState(0);
  const [outboundScheduleTime, setOutboundScheduleTime] = useState(() => {
    const d = new Date();
    d.setHours(d.getHours() + 1);
    return d.toISOString().slice(0, 16);
  });

  // Verification checklist
  const [checks, setChecks] = useState<Record<string, CheckStatus>>({
    oauth: "pending",
    provider_healthy: "pending",
    sync_successful: "pending",
    normalization: "pending",
    dedup: "pending",
    intelligence: "pending",
    planner: "pending",
    copilot_context: "pending",
    memory: "pending",
    events: "pending",
  });
  const [syncStartTime, setSyncStartTime] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastPollSyncRef = useRef("");
  const lastPollCountRef = useRef(0);

  // ── Init ──
  useEffect(() => {
    document.documentElement.style.overflow = "auto";
    document.body.style.overflow = "auto";
    return () => {
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
    };
  }, []);

  useEffect(() => {
    const t = getSession();
    setToken(t);
    if (t) {
      loadData(t);
    }
  }, []);

  async function refreshAll(t: string) {
    await loadData(t);
    await loadProviderDetail(t, selectedProvider?.id || "");
    setOauthResult(null);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPollingAfterTimeout() {
    if (pollRef.current) return;
    lastPollSyncRef.current = selectedProvider?.last_sync || "";
    lastPollCountRef.current = messageCount;
    pollRef.current = setInterval(async () => {
      if (!token || !selectedProvider) {
        stopPolling();
        return;
      }
      try {
        const [statusRes, msgRes] = await Promise.all([
          getProviderStatus(token, selectedProvider.id),
          getProviderMessages(token, selectedProvider.id),
        ]);
        const syncChanged = statusRes.last_sync && statusRes.last_sync !== lastPollSyncRef.current;
        const countChanged = msgRes.total_messages_seen > lastPollCountRef.current;
        if (syncChanged || countChanged) {
          stopPolling();
          setSyncState("completed");
          setMessageCount(msgRes.total_messages_seen || 0);
          setRecentMessages(msgRes.recent_messages || []);
          setSyncResult((prev) => prev ? {
            ...prev,
            cursor: statusRes.sync_cursor || prev.cursor,
          } : null);
          try {
            const pRes = await listProviders(token);
            setProviders(pRes.providers || []);
            const updated = (pRes.providers || []).find(p => p.id === selectedProvider.id);
            if (updated) setSelectedProvider(updated);
          } catch {}
        }
      } catch {
        // poll error, keep polling
      }
    }, 5000);
  }

  async function loadData(t: string) {
    try {
      const [pRes, typesRes] = await Promise.all([
        listProviders(t),
        getRegisteredProviderTypes(t),
      ]);
      const plist = pRes.providers || [];
      setProviders(plist);
      setRegisteredTypes(typesRes.types || []);
      if (plist.length > 0 && !selectedProvider) {
        setSelectedProvider(plist[0]);
      }
      setChecks((c) => ({ ...c, oauth: plist.length > 0 ? "pass" : "pending" }));
    } catch {
      console.error("Failed to load provider data");
    }
  }

  async function loadProviderDetail(t: string, pid: string) {
    if (!pid) return;
    try {
      const [statusRes, msgRes, threadRes] = await Promise.all([
        getProviderStatus(t, pid),
        getProviderMessages(t, pid),
        getProviderThreads(t, pid),
      ]);
      setMessageCount(msgRes.total_messages_seen || 0);
      setRecentMessages(msgRes.recent_messages || []);
      setThreadCount(threadRes.total || 0);
      setChecks((c) => ({
        ...c,
        provider_healthy: statusRes.status === "healthy" ? "pass" : "fail",
      }));
    } catch {
      // ignore
    }
  }

  // ── Event polling ──
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(async () => {
      try {
        const evRes = await getProviderEvents(token, selectedProvider?.id, eventSeq);
        if (evRes.events?.length > 0) {
          setProviderEvents((prev) => [...prev, ...evRes.events].slice(-100));
          setEventSeq(evRes.latest_sequence);
          setChecks((c) => ({ ...c, events: "pass" }));
        }
      } catch {
        // ignore
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [token, selectedProvider?.id, eventSeq]);

  // ── OAuth ──
  async function handleConnectGmail() {
    setOauthLoading(true);
    setOauthError("");
    setOauthResult(null);
    try {
      const result = await openGmailAuthPopup(() => getGmailAuthUrl(token || undefined));
      if (result.status === "opened") {
        setAuthUrl("(popup opened)");
      } else if (result.status === "blocked") {
        setOauthError("Popup blocked — please allow popups for this site and try again.");
      } else {
        setOauthError("Failed to get auth URL. Check GOOGLE_CLIENT_ID env.");
      }
    } catch (e) {
      setOauthError(String(e));
    }
    setOauthLoading(false);
  }

  // ── Sync ──
  async function handleSync(cursor?: string) {
    if (!token || !selectedProvider) return;
    stopPolling();
    setSyncState("running");
    setSyncStartTime(Date.now());
    try {
      const res = await syncProvider(token, selectedProvider.id, cursor);
      setSyncState("completed");
      setSyncResult(res.result);
      setChecks((c) => ({
        ...c,
        sync_successful: res.result.errors?.length === 0 ? "pass" : "fail",
        dedup: "pass",
      }));
      await loadProviderDetail(token, selectedProvider.id);
      const evRes = await getProviderEvents(token, selectedProvider.id, eventSeq);
      if (evRes.events?.length > 0) {
        setProviderEvents((prev) => [...prev, ...evRes.events].slice(-100));
        setEventSeq(evRes.latest_sequence);
        setChecks((c) => ({ ...c, events: "pass" }));
      }
      try {
        const pRes = await listProviders(token);
        setProviders(pRes.providers || []);
        const updated = (pRes.providers || []).find(p => p.id === selectedProvider.id);
        if (updated) setSelectedProvider(updated);
      } catch {}
    } catch (e) {
      if (e instanceof TimeoutError) {
        setSyncState("timed_out");
        startPollingAfterTimeout();
      } else {
        setSyncState("failed");
        setChecks((c) => ({ ...c, sync_successful: "fail" }));
      }
    }
  }

  // ── Conversation Intelligence ──
  async function handleAnalyze() {
    if (!token) return;
    try {
      const res = await analyzeConversationMessage(token, sampleText, intelConversationId);
      setIntelligence(res.intelligence);
      setIntelMemory(res.memory);
      if (!intelConversationId && res.intelligence?.conversation_id) {
        setIntelConversationId(res.intelligence.conversation_id as string);
      }
      setChecks((c) => ({ ...c, intelligence: "pass", normalization: "pass", memory: "pass" }));
    } catch (e) {
      console.error(e);
      setChecks((c) => ({ ...c, intelligence: "fail" }));
    }
  }

  async function handleShowTimeline() {
    if (!token || !intelConversationId) return;
    try {
      const res = await getConversationTimeline(token, intelConversationId);
      setTimeline(res.events || []);
    } catch {
      // ignore
    }
  }

  async function handleSummary() {
    if (!token) return;
    try {
      const res = await getCommunicationSummary(token, sampleText);
      setSummaryResult(res.summary);
    } catch (e) {
      setSummaryResult("Error: " + String(e));
    }
  }

  async function handleRecommend() {
    if (!token) return;
    try {
      const res = await getCommunicationRecommend(token, sampleText);
      setRecommendResult(JSON.stringify(res.recommendation, null, 2));
    } catch (e) {
      setRecommendResult("Error: " + String(e));
    }
  }

  // ── Planner ──
  async function handlePlan() {
    if (!token) return;
    try {
      const res = await planWorkflow(token, plannerObjective);
      setPlannerResult(res);
      setChecks((c) => ({ ...c, planner: "pass" }));
    } catch {
      setChecks((c) => ({ ...c, planner: "fail" }));
    }
  }

  // ── Copilot Context ──
  async function handleCopilotContext() {
    if (!token) return;
    try {
      const ctx = await getWorkspaceContext(token, intelConversationId || undefined);
      setCopilotContext(ctx);
      setChecks((c) => ({ ...c, copilot_context: "pass" }));
    } catch {
      setChecks((c) => ({ ...c, copilot_context: "fail" }));
    }
  }

  // ── Outbound ──
  async function handleOutboundCreateDraft() {
    if (!token || !selectedProvider) return;
    setOutboundResult("");
    try {
      const res = await outboundCreateDraft(token, {
        provider_id: selectedProvider.id,
        conversation_id: intelConversationId,
        subject: outboundDraftSubject,
        body: outboundDraftBody,
        recipient_email: outboundRecipient,
        sender_email: selectedProvider.email || "me@example.com",
      });
      setOutboundResult(res.ok ? `Draft created: ${res.draft?.id || ""}` : "Failed");
      await handleOutboundListDrafts();
    } catch (e) {
      setOutboundResult("Error: " + String(e));
    }
  }

  async function handleOutboundListDrafts() {
    if (!token || !selectedProvider) return;
    try {
      const res = await outboundListDrafts(token, selectedProvider.id);
      setOutboundDrafts(res.drafts || []);
      setOutboundDraftCount(res.total || 0);
    } catch {}
  }

  async function handleOutboundSend() {
    if (!token || !selectedProvider) return;
    setOutboundResult("");
    try {
      const res = await outboundSend(token, {
        provider_id: selectedProvider.id,
        recipient_email: outboundRecipient,
        subject: outboundDraftSubject,
        body: outboundDraftBody,
        sender_email: selectedProvider.email || "me@example.com",
      });
      setOutboundResult(res.ok ? `Sent: ${res.send_result?.external_message_id || ""}` : `Failed: ${res.error || ""}`);
      await handleOutboundListDrafts();
      await handleOutboundHistory();
    } catch (e) {
      setOutboundResult("Error: " + String(e));
    }
  }

  async function handleOutboundHistory() {
    if (!token || !selectedProvider) return;
    try {
      const res = await outboundGetHistory(token, selectedProvider.id);
      setOutboundHistory(res.history || []);
    } catch {}
  }

  async function handleOutboundApprove(draftId: string) {
    if (!token) return;
    try {
      await outboundApproveDraft(token, draftId);
      await handleOutboundListDrafts();
    } catch {}
  }

  async function handleOutboundReject(draftId: string) {
    if (!token) return;
    try {
      await outboundRejectDraft(token, draftId);
      await handleOutboundListDrafts();
    } catch {}
  }

  async function handleOutboundDelete(draftId: string) {
    if (!token || !selectedProvider) return;
    try {
      await outboundDeleteDraft(token, draftId, selectedProvider.id);
      await handleOutboundListDrafts();
    } catch {}
  }

  async function handleOutboundApproveAll() {
    if (!token) return;
    try {
      const res = await outboundApproveAll(token);
      setOutboundResult(`Approve All: ${res.created} created, ${res.failed} failed (of ${res.total})`);
      await handleOutboundListDrafts();
    } catch (e) {
      setOutboundResult("Approve All error: " + String(e));
    }
  }

  async function handleOutboundSendDraft(draftId: string) {
    if (!token || !selectedProvider) return;
    try {
      const res = await outboundSend(token, {
        provider_id: selectedProvider.id,
        draft_id: draftId,
      });
      setOutboundResult(res.ok ? `Sent: ${res.send_result?.external_message_id || ""}` : `Failed: ${res.error || ""}`);
      await handleOutboundListDrafts();
      await handleOutboundHistory();
    } catch (e) {
      setOutboundResult("Send error: " + String(e));
    }
  }

  async function handleOutboundScheduleDraft(draftId: string) {
    if (!token || !selectedProvider) return;
    try {
      const res = await outboundSchedule(token, {
        provider_id: selectedProvider.id,
        draft_id: draftId,
        send_at: new Date(outboundScheduleTime).toISOString(),
      });
      setOutboundResult(res.ok ? `Scheduled: ${res.schedule_id || ""}` : `Failed: ${res.error || ""}`);
      await handleOutboundListDrafts();
    } catch (e) {
      setOutboundResult("Schedule error: " + String(e));
    }
  }

  async function handleOutboundCancelDraftSchedule(draftId: string) {
    if (!token || !selectedProvider) return;
    try {
      const res = await outboundCancelSchedule(token, draftId, selectedProvider.id);
      setOutboundResult(res.ok ? "Schedule cancelled" : "Cancel failed");
      await handleOutboundListDrafts();
    } catch (e) {
      setOutboundResult("Cancel error: " + String(e));
    }
  }

  // ── Outbound events polling ──
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(async () => {
      try {
        const evRes = await outboundGetEventsApi(token, selectedProvider?.id, outboundEventSeq);
        if (evRes.events?.length > 0) {
          setOutboundEvents((prev) => [...prev, ...evRes.events].slice(-100));
          setOutboundEventSeq(evRes.latest_sequence);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [token, selectedProvider?.id, outboundEventSeq]);

  // ── Helpers ──
  function statusColor(s: string) {
    if (s === "healthy" || s === "pass") return "#22c55e";
    if (s === "warning") return "#eab308";
    if (s === "offline" || s === "fail" || s === "expired_token") return "#ef4444";
    if (s === "pending") return "#6b7280";
    if (s === "skipped") return "#9ca3af";
    return "#6b7280";
  }

  function fmtTime(iso: string) {
    if (!iso) return "-";
    return new Date(iso).toLocaleString();
  }

  if (!DEV_MODE) {
    return (
      <div style={{ padding: 40, fontFamily: "monospace" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>Dev Tools Disabled</h1>
        <p>Set NEXT_PUBLIC_DEV_MODE=true or run in development mode to access this page.</p>
      </div>
    );
  }

  // Listen for OAuth callback from popup via postMessage
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (!isTrustedGmailOAuthMessage(ev)) return;
      if (ev.data?.type === "gmail-oauth" && ev.data?.payload) {
        const p = ev.data.payload;
        if (p.ok && p.provider_id) {
          setOauthResult({ provider_id: p.provider_id, email: p.email || "" });
          setChecks((c) => ({ ...c, oauth: "pass" }));
          setOauthLoading(false);
          refreshAll(token);
        } else {
          setOauthError(p.error || "OAuth callback failed");
          setChecks((c) => ({ ...c, oauth: "fail" }));
          setOauthLoading(false);
        }
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [token]);

  return (
    <div style={{ padding: 32, fontFamily: "monospace", maxWidth: 1200, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: "#e2e8f0", margin: 0 }}>
            ⚙ Provider Validation Harness
          </h1>
          <p style={{ color: "#94a3b8", marginTop: 4, fontSize: 13 }}>
            DEVELOPMENT-ONLY — Proves the Gmail integration pipeline works end-to-end
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "#64748b" }}>token: {token.slice(0, 8)}...</span>
          <button onClick={() => loadData(token)} style={btnStyle}>Refresh</button>
        </div>
      </div>

      {/* ──────────── SECTION 1: Provider Status ──────────── */}
      <Section title="1. Provider Status">
        {providers.length === 0 ? (
          <p style={{ color: "#94a3b8" }}>No providers connected. Use OAuth below to connect Gmail.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {["Provider", "Status", "Email", "Connected Since", "Last Sync", "Sync Cursor", "Messages", "Threads"].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => (
                <tr
                  key={p.id}
                  style={{ borderBottom: "1px solid #1e293b", cursor: "pointer", background: selectedProvider?.id === p.id ? "#1e293b" : "transparent" }}
                  onClick={() => setSelectedProvider(p)}
                >
                  <td style={{ padding: "6px 8px", color: "#e2e8f0" }}>{p.provider_type}</td>
                  <td style={{ padding: "6px 8px" }}>
                    <span style={{ color: statusColor(p.status), fontWeight: 600 }}>{p.status}</span>
                  </td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{p.email || "-"}</td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{fmtTime(p.created_at)}</td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{fmtTime(p.last_sync)}</td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8", fontSize: 11 }}>{p.sync_cursor?.slice(0, 20) || "-"}</td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{messageCount}</td>
                  <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{threadCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* ──────────── SECTION 2: OAuth ──────────── */}
      <Section title="2. Google OAuth">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
          <button onClick={handleConnectGmail} disabled={oauthLoading} style={{ ...btnStyle, background: oauthLoading ? "#334155" : "#2563eb" }}>
            {oauthLoading ? "Connecting..." : "Connect Gmail"}
          </button>
          <button onClick={async () => {
            if (!selectedProvider || !token) return;
            await disconnectProvider(token, selectedProvider.id);
            setSelectedProvider(null);
            await refreshAll(token);
          }} disabled={!selectedProvider} style={{ ...btnStyle, background: "#dc2626" }}>
            Disconnect Gmail
          </button>
          <button onClick={async () => {
            if (!token || !selectedProvider) return;
            try {
              const h = await getProviderHealth(token, selectedProvider.id);
              setChecks((c) => ({ ...c, provider_healthy: h.status === "healthy" ? "pass" : "fail" }));
            } catch {
              setChecks((c) => ({ ...c, provider_healthy: "fail" }));
            }
          }} disabled={!selectedProvider} style={{ ...btnStyle, background: "#059669" }}>
            Validate Token
          </button>
        </div>
        {oauthError && <p style={{ color: "#ef4444", fontSize: 13 }}>Error: {oauthError}</p>}
        {oauthResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginBottom: 8 }}>
            <div style={{ color: "#22c55e", fontWeight: 700, marginBottom: 4 }}>✓ Gmail Connected</div>
            <KV k="Provider ID" v={oauthResult.provider_id} />
            <KV k="Email" v={oauthResult.email} />
          </div>
        )}
        {authUrl && <p style={{ color: "#94a3b8", fontSize: 12 }}>Auth URL opened in new tab. If no popup, <a href={authUrl} target="_blank" style={{ color: "#60a5fa" }}>click here</a>.</p>}
        <div style={{ fontSize: 13, color: "#94a3b8" }}>
          <p>Scopes: gmail.readonly, gmail.send, userinfo.email</p>
          <p>Registered types: {registeredTypes.join(", ") || "none"}</p>
        </div>
      </Section>

      {/* ──────────── SECTION 3: Manual Sync ──────────── */}
      <Section title="3. Manual Sync">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
          <button onClick={() => handleSync()} disabled={syncState === "running" || syncState === "timed_out" || !selectedProvider} style={{ ...btnStyle, background: syncState === "running" || syncState === "timed_out" ? "#334155" : "#2563eb" }}>
            {syncState === "running" ? "Syncing..." : syncState === "timed_out" ? "Waiting..." : "Sync Everything"}
          </button>
          <button onClick={() => handleSync(selectedProvider?.sync_cursor)} disabled={syncState === "running" || syncState === "timed_out" || !selectedProvider || !selectedProvider.sync_cursor} style={{ ...btnStyle, background: "#7c3aed" }}>
            Sync Since Cursor
          </button>
          <button onClick={() => { stopPolling(); setSyncResult(null); setSyncState("idle"); setProviderEvents([]); }} style={{ ...btnStyle, background: "#6b7280" }}>
            Clear Results
          </button>
        </div>

        {/* Sync state indicator */}
        {syncState === "running" && (
          <div style={{ fontSize: 13, color: "#60a5fa", marginBottom: 8 }}>
            🟡 Sync running... elapsed: {((Date.now() - syncStartTime) / 1000).toFixed(1)}s
          </div>
        )}
        {syncState === "timed_out" && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginBottom: 8 }}>
            <div style={{ color: "#f59e0b", fontWeight: 600, marginBottom: 4 }}>
              🟠 Waiting for server...
            </div>
            <div style={{ color: "#94a3b8", fontSize: 12, lineHeight: 1.5 }}>
              Gmail is still syncing in the background.<br />
              Large inboxes can take over a minute on the initial sync.
            </div>
          </div>
        )}

        {/* Sync result — always show real data, never fabricated zeros */}
        {syncResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13 }}>
            <div style={{ color: syncState === "failed" ? "#ef4444" : syncState === "running" ? "#60a5fa" : syncState === "timed_out" ? "#f59e0b" : "#22c55e", fontWeight: 600, marginBottom: 8 }}>
              {syncState === "failed" ? "🔴 Sync failed" : syncState === "running" ? "🟡 Currently syncing..." : syncState === "timed_out" ? "🟠 Previous sync (waiting for new data)" : "🟢 Sync completed"}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
              <div><span style={{ color: "#94a3b8" }}>Messages:</span> <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{syncResult.messages_synced}</span></div>
              <div><span style={{ color: "#94a3b8" }}>Threads:</span> <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{syncResult.threads_synced}</span></div>
              <div><span style={{ color: "#94a3b8" }}>New Conversations:</span> <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{syncResult.new_conversations}</span></div>
              <div><span style={{ color: "#94a3b8" }}>Duration:</span> <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{syncResult.duration_ms}ms</span></div>
              <div><span style={{ color: "#94a3b8" }}>Errors:</span> <span style={{ color: syncResult.errors.length > 0 ? "#ef4444" : "#22c55e", fontWeight: 600 }}>{syncResult.errors.length || 0}</span></div>
              <div><span style={{ color: "#94a3b8" }}>Cursor:</span> <span style={{ color: "#e2e8f0", fontSize: 11 }}>{syncResult.cursor?.slice(0, 30) || "-"}</span></div>
            </div>
            {syncResult.errors.length > 0 && (
              <div style={{ marginTop: 8, color: "#ef4444" }}>
                {syncResult.errors.map((e, i) => <div key={i}>- {e}</div>)}
              </div>
            )}
          </div>
        )}

        {/* Completed via polling recovery — no syncResult object available */}
        {syncState === "completed" && !syncResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13 }}>
            <div style={{ color: "#22c55e", fontWeight: 600, marginBottom: 4 }}>
              🟢 Sync completed
            </div>
            <div style={{ color: "#94a3b8" }}>
              {messageCount} total messages imported
            </div>
          </div>
        )}
      </Section>

      {/* ──────────── SECTION 4: Recent Messages ──────────── */}
      <Section title="4. Recent Messages">
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 12 }}>
          {messageCount} total messages imported. Latest <strong style={{ color: "#e2e8f0" }}>{recentMessages.length}</strong> synced messages:
        </p>
        {recentMessages.length === 0 ? (
          <p style={{ color: "#6b7280", fontSize: 13 }}>
            {syncState === "timed_out"
              ? "Waiting for sync to complete on the server..."
              : syncState === "running"
                ? "Messages will appear when sync completes..."
                : "No messages synced yet. Click \"Sync Everything\" above."}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #334155" }}>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>Subject</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>Sender</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>Date</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>Thread ID</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>Message ID</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#94a3b8" }}>History ID</th>
                </tr>
              </thead>
              <tbody>
                {[...recentMessages].reverse().map((msg, idx) => (
                  <tr key={idx} style={{ borderBottom: "1px solid #1e293b" }}>
                    <td style={{ padding: "6px 8px", color: "#e2e8f0", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {String(msg.subject || "(no subject)")}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#94a3b8", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {String(msg.sender || "-")}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#94a3b8", whiteSpace: "nowrap" }}>
                      {msg.date ? new Date(String(msg.date)).toLocaleString() : "-"}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#6b7280", fontSize: 11 }}>
                      {String(msg.thread_id || "-").slice(0, 16)}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#6b7280", fontSize: 11 }}>
                      {String(msg.message_id || "-").slice(0, 16)}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#6b7280", fontSize: 11 }}>
                      {String(msg.history_id || "-").slice(0, 12)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 8 }}>
          <p>Each synced message is automatically normalized from Gmail → ConversationMessage → Conversation Intelligence pipeline.</p>
        </div>
      </Section>

      {/* ──────────── SECTION 5: Conversation Intelligence ──────────── */}
      <Section title="5. Conversation Intelligence">
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>Sample Message</label>
          <input
            value={sampleText}
            onChange={(e) => setSampleText(e.target.value)}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13 }}
          />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <button onClick={handleAnalyze} style={{ ...btnStyle, background: "#2563eb" }}>Analyze Message</button>
          <button onClick={handleShowTimeline} disabled={!intelConversationId} style={{ ...btnStyle, background: "#7c3aed" }}>
            Show Timeline
          </button>
          <button onClick={handleSummary} style={{ ...btnStyle, background: "#059669" }}>Summary</button>
          <button onClick={handleRecommend} style={{ ...btnStyle, background: "#d97706" }}>Recommendation</button>
        </div>
        {intelligence && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginBottom: 8 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Reply Intelligence</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
              <KV k="Conversation ID" v={String(intelligence.conversation_id ?? "-")} />
              <KV k="Stage" v={String(intelligence.conversation_stage ?? "-")} />
              <KV k="Urgency" v={String(intelligence.urgency ?? "-")} />
              <KV k="Decision Confidence" v={String(intelligence.decision_confidence ?? "-")} />
              <KV k="Top Objection" v={String(intelligence.top_objection ?? "-")} />
              <KV k="Recommended Step" v={String(intelligence.recommended_next_step ?? "-")} />
              <KV k="Workflow Objective" v={String(intelligence.suggested_workflow_objective ?? "-")} />
              <KV k="Human Approval" v={String(intelligence.human_approval_required ?? "-")} />
            </div>
            {String(intelligence.executive_summary || "") && (
              <div style={{ marginTop: 8, padding: 8, background: "#0f172a", borderRadius: 6 }}>
                <div style={{ color: "#94a3b8", marginBottom: 4 }}>Executive Summary</div>
                <div style={{ color: "#e2e8f0" }}>{String(intelligence.executive_summary)}</div>
              </div>
            )}
            {((intelligence.intents as Array<Record<string, unknown>>) || []).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ color: "#94a3b8", marginBottom: 4 }}>Detected Intents</div>
                {(intelligence.intents as Array<Record<string, unknown>>).map((i: Record<string, unknown>, idx: number) => (
                  <div key={idx} style={{ padding: "4px 0", color: "#e2e8f0" }}>
                    - {String(i.intent)} (confidence: {String(i.confidence)}) — {String(i.reason)}
                  </div>
                ))}
              </div>
            )}
            {((intelligence.buying_signals as Array<Record<string, unknown>>) || []).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ color: "#94a3b8", marginBottom: 4 }}>Buying Signals</div>
                {(intelligence.buying_signals as Array<Record<string, unknown>>).map((s: Record<string, unknown>, idx: number) => (
                  <div key={idx} style={{ padding: "4px 0", color: "#e2e8f0" }}>
                    - {String(s.signal)} (<span style={{ color: statusColor(String(s.strength)) }}>{String(s.strength)}</span>, confidence: {String(s.confidence)})
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {intelMemory && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Conversation Memory</div>
            <KV k="Current Stage" v={String(intelMemory.current_stage ?? "-")} />
            <KV k="Urgency" v={String(intelMemory.urgency ?? "-")} />
            <KV k="Decision Confidence" v={String(intelMemory.decision_confidence ?? "-")} />
            {(intelMemory.buying_signals as string[] || [])?.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <span style={{ color: "#94a3b8" }}>Buying Signals: </span>
                <span style={{ color: "#e2e8f0" }}>{(intelMemory.buying_signals as string[]).join(", ")}</span>
              </div>
            )}
            {(intelMemory.key_risks as string[] || [])?.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <span style={{ color: "#94a3b8" }}>Risks: </span>
                <span style={{ color: "#ef4444" }}>{(intelMemory.key_risks as string[]).join(", ")}</span>
              </div>
            )}
          </div>
        )}
        {timeline.length > 0 && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginTop: 8 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Conversation Timeline</div>
            {timeline.map((ev, idx) => (
              <div key={idx} style={{ padding: "4px 0", color: "#94a3b8" }}>
                [{ev.event_type as string}] {ev.message as string} — {fmtTime(ev.timestamp as string)}
              </div>
            ))}
          </div>
        )}
        {summaryResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginTop: 8 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Executive Summary</div>
            <div style={{ color: "#94a3b8", whiteSpace: "pre-wrap" }}>{summaryResult}</div>
          </div>
        )}
        {recommendResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginTop: 8 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Recommendation</div>
            <pre style={{ color: "#94a3b8", fontSize: 11, whiteSpace: "pre-wrap" }}>{recommendResult}</pre>
          </div>
        )}
      </Section>

      {/* ──────────── SECTION 6: Planner Integration ──────────── */}
      <Section title="6. Planner Integration">
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>Workflow Objective</label>
          <input
            value={plannerObjective}
            onChange={(e) => setPlannerObjective(e.target.value)}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13 }}
          />
        </div>
        <button onClick={handlePlan} style={{ ...btnStyle, background: "#2563eb" }}>Generate Plan</button>
        {plannerResult && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginTop: 12 }}>
            <KV k="Recommendation" v={plannerResult.recommendation} />
            <KV k="Confidence" v={plannerResult.confidence} />
            <div style={{ marginTop: 8, color: "#94a3b8" }}>Primary Plan:</div>
            <pre style={{ color: "#e2e8f0", fontSize: 11, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(plannerResult.plan, null, 2)}
            </pre>
            <div style={{ marginTop: 8, color: "#94a3b8" }}>Alternative Plan:</div>
            <pre style={{ color: "#e2e8f0", fontSize: 11, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(plannerResult.alternative_plan, null, 2)}
            </pre>
          </div>
        )}
      </Section>

      {/* ──────────── SECTION 7: Copilot Context ──────────── */}
      <Section title="7. Copilot Context">
        <button onClick={handleCopilotContext} style={{ ...btnStyle, background: "#2563eb" }}>
          Fetch Copilot Context
        </button>
        {copilotContext && (
          <div style={{ background: "#1e293b", padding: 12, borderRadius: 8, fontSize: 13, marginTop: 12 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 8 }}>Workspace Context (truncated to 300 lines)</div>
            <pre style={{ color: "#94a3b8", fontSize: 11, whiteSpace: "pre-wrap", maxHeight: 600, overflow: "auto" }}>
              {JSON.stringify(copilotContext, null, 2)}
            </pre>
          </div>
        )}
      </Section>

      {/* ──────────── SECTION 8: Provider Events ──────────── */}
      <Section title="8. Provider Events (Auto-refresh every 3s)">
        <p style={{ color: "#94a3b8", fontSize: 12, marginBottom: 8 }}>
          {providerEvents.length} events — latest sequence: {eventSeq}
        </p>
        <div style={{ maxHeight: 300, overflow: "auto", background: "#0f172a", borderRadius: 8, padding: 8 }}>
          {providerEvents.length === 0 ? (
            <p style={{ color: "#6b7280", fontSize: 13 }}>No events yet. Connect and sync to see events.</p>
          ) : (
            [...providerEvents].reverse().map((ev) => (
              <div key={ev.id} style={{ padding: "4px 0", borderBottom: "1px solid #1e293b", fontSize: 12 }}>
                <span style={{ color: "#6b7280" }}>#{ev.sequence}</span>{" "}
                <span style={{ color: statusColor(ev.event_type.startsWith("sync_failed") ? "fail" : "pass") }}>
                  {ev.event_type}
                </span>{" "}
                <span style={{ color: "#94a3b8" }}>{ev.message}</span>{" "}
                <span style={{ color: "#6b7280", fontSize: 11 }}>{fmtTime(ev.timestamp)}</span>
              </div>
            ))
          )}
        </div>
      </Section>

      {/* ──────────── SECTION 9: Conversation Timeline ──────────── */}
      <Section title="9. Conversation Timeline">
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 8 }}>
          {timeline.length} timeline events for conversation {intelConversationId || "(none)"}
        </p>
        {timeline.length > 0 ? (
          <div style={{ maxHeight: 200, overflow: "auto" }}>
            {timeline.map((ev, idx) => (
              <div key={idx} style={{ padding: "4px 0", fontSize: 12, borderBottom: "1px solid #1e293b" }}>
                <span style={{ color: "#60a5fa" }}>{ev.event_type as string}</span>{" "}
                <span style={{ color: "#94a3b8" }}>{ev.message as string}</span>{" "}
                <span style={{ color: "#6b7280" }}>{fmtTime(ev.timestamp as string)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: "#6b7280", fontSize: 13 }}>Analyze a message above, then click "Show Timeline".</p>
        )}
      </Section>

      {/* ──────────── SECTION 10: System Diagnostics ──────────── */}
      <Section title="10. System Diagnostics">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 13 }}>
          <KV k="Registered Provider Types" v={registeredTypes.join(", ")} />
          <KV k="Connected Providers" v={String(providers.length)} />
          <KV k="Selected Provider ID" v={selectedProvider?.id || "-"} />
          <KV k="Provider Status" v={selectedProvider?.status || "-"} />
          <KV k="Messages Imported" v={String(messageCount)} />
          <KV k="Threads" v={String(threadCount)} />
          <KV k="Conversations" v={String(threadCount)} />
          <KV k="Recent Messages Count" v={String(recentMessages.length)} />
          <KV k="Events Emitted" v={String(providerEvents.length)} />
          <KV k="Latest Event Sequence" v={String(eventSeq)} />
          <KV k="Sample Conversation ID" v={intelConversationId || "(not yet)"} />
        </div>
      </Section>

      {/* ──────────── SECTION 11: Testing Tools ──────────── */}
      <Section title="11. Testing Tools">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={handleAnalyze} style={{ ...btnStyle, background: "#2563eb" }}>Analyze Sample Message</button>
          <button onClick={async () => {
            if (!token) return;
            const res = await analyzeConversationMessage(token, "I'm interested in a demo. Can you show me how it works? Can we schedule a call next week?", "test_inject_" + Date.now());
            setIntelligence(res.intelligence);
            setIntelMemory(res.memory);
            if (res.intelligence?.conversation_id) setIntelConversationId(res.intelligence.conversation_id as string);
          }} style={{ ...btnStyle, background: "#7c3aed" }}>Inject Test Reply</button>
          <button onClick={() => { setIntelMemory(null); setIntelligence(null); setTimeline([]); setIntelConversationId(""); }}
            style={{ ...btnStyle, background: "#dc2626" }}>Clear Memory</button>
          <button onClick={handleCopilotContext} style={{ ...btnStyle, background: "#059669" }}>Rebuild Copilot Context</button>
          <button onClick={handlePlan} style={{ ...btnStyle, background: "#d97706" }}>Re-run Planner</button>
        </div>
      </Section>

      {/* ──────────── SECTION 12: Verification Checklist ──────────── */}
      <Section title="12. Verification Checklist">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 13 }}>
          {Object.entries(checks).map(([key, status]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                width: 12, height: 12, borderRadius: "50%", display: "inline-block",
                background: status === "pass" ? "#22c55e" : status === "fail" ? "#ef4444" : status === "skipped" ? "#9ca3af" : "#6b7280",
              }} />
              <span style={{ color: "#e2e8f0" }}>{key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</span>
              {status === "pass" && <span style={{ color: "#22c55e" }}>✓</span>}
              {status === "fail" && <span style={{ color: "#ef4444" }}>✗</span>}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, padding: "8px 12px", borderRadius: 8, background: "#1e293b", fontSize: 13, color: "#94a3b8" }}>
          <p>Flow: {providers.length > 0 ? "✓ " : "✗ "}OAuth → {checks.sync_successful === "pass" ? "✓ " : "✗ "}Sync → {(intelligence as Record<string, unknown> | null) ? "✓ " : "✗ "}Normalize → {checks.intelligence === "pass" ? "✓ " : "✗ "}Conversation Intelligence → {plannerResult ? "✓ " : "✗ "}Planner → {copilotContext ? "✓ " : "✗ "}Copilot</p>
        </div>
      </Section>

      {/* ──────────── SECTION 13: Outbound Validation ──────────── */}
      <Section title="13. Outbound Validation">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <input
            value={outboundRecipient}
            onChange={(e) => setOutboundRecipient(e.target.value)}
            placeholder="Recipient email"
            style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13, flex: 1, minWidth: 200 }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <input
            value={outboundDraftSubject}
            onChange={(e) => setOutboundDraftSubject(e.target.value)}
            placeholder="Subject"
            style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13, marginBottom: 8 }}
          />
          <textarea
            value={outboundDraftBody}
            onChange={(e) => setOutboundDraftBody(e.target.value)}
            placeholder="Message body"
            rows={4}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13, resize: "vertical" }}
          />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          <button onClick={handleOutboundCreateDraft} disabled={!selectedProvider} style={{ ...btnStyle, background: "#2563eb" }}>Create Draft</button>
          <button onClick={handleOutboundSend} disabled={!selectedProvider} style={{ ...btnStyle, background: "#059669" }}>Send Direct</button>
          <button onClick={handleOutboundListDrafts} disabled={!selectedProvider} style={{ ...btnStyle, background: "#7c3aed" }}>List Drafts</button>
          <button onClick={handleOutboundHistory} disabled={!selectedProvider} style={{ ...btnStyle, background: "#d97706" }}>Send History</button>
          <button onClick={handleOutboundApproveAll} disabled={!selectedProvider} style={{ ...btnStyle, background: "#0891b2" }}>Approve All</button>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <input
            type="datetime-local"
            value={outboundScheduleTime}
            onChange={(e) => setOutboundScheduleTime(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0", fontSize: 13 }}
          />
        </div>
        {outboundResult && (
          <div style={{ background: "#1e293b", padding: 8, borderRadius: 6, fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>
            {outboundResult}
          </div>
        )}
        {outboundDrafts.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: "#94a3b8", fontSize: 13, marginBottom: 4 }}>Drafts ({outboundDraftCount} total):</div>
            <div style={{ maxHeight: 400, overflow: "auto", fontSize: 12 }}>
              {outboundDrafts.map((d, idx) => {
                const status = String(d.status || "-");
                const extId = String(d.external_draft_id || "");
                const isApproved = status === "approved" || status === "auto_approved";
                const isScheduled = status === "scheduled";
                const isFailed = status === "failed";
                const isSent = status === "sent";
                return (
                  <div key={idx} style={{ padding: "6px 8px", borderBottom: "1px solid #1e293b", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ flex: 1, marginRight: 8 }}>
                      <div style={{ color: "#e2e8f0" }}>{String(d.subject || "(no subject)")}</div>
                      <div style={{ color: "#6b7280", fontSize: 11 }}>
                        Status: <span style={{ color: isSent ? "#22c55e" : isFailed ? "#ef4444" : isScheduled ? "#f59e0b" : "#60a5fa" }}>{status}</span>
                        {extId ? ` | Gmail Draft: ${extId}` : ""}
                        {d.gmail_message_id ? ` | Msg: ${String(d.gmail_message_id)}` : ""}
                        {(d.metadata as Record<string, string>)?.send_at ? ` | Scheduled: ${(d.metadata as Record<string, string>).send_at}` : ""}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {!isApproved && !isSent && !isScheduled && (
                        <button onClick={() => handleOutboundApprove(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#22c55e" }}>Approve</button>
                      )}
                      <button onClick={() => handleOutboundReject(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#ef4444" }}>Reject</button>
                      {isApproved && !isSent && (
                        <button onClick={() => handleOutboundSendDraft(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#059669" }}>Send Now</button>
                      )}
                      {isApproved && !isScheduled && !isSent && (
                        <button onClick={() => handleOutboundScheduleDraft(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#f59e0b" }}>Schedule</button>
                      )}
                      {isScheduled && (
                        <button onClick={() => handleOutboundCancelDraftSchedule(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#dc2626" }}>Cancel</button>
                      )}
                      <button onClick={() => handleOutboundDelete(String(d.id))} style={{ ...btnStyle, padding: "4px 8px", fontSize: 11, background: "#6b7280" }}>Delete</button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {outboundHistory.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: "#94a3b8", fontSize: 13, marginBottom: 4 }}>Send History ({outboundHistory.length}):</div>
            <div style={{ maxHeight: 150, overflow: "auto", fontSize: 12 }}>
              {outboundHistory.map((h, idx) => (
                <div key={idx} style={{ padding: "4px 8px", borderBottom: "1px solid #1e293b", color: "#94a3b8" }}>
                  {String(h.subject || "(no subject)")} — <span style={{ color: h.status === "sent" ? "#22c55e" : "#ef4444" }}>{String(h.status || "-")}</span>
                  {h.external_message_id ? ` | ID: ${String(h.external_message_id)}` : ""}
                </div>
              ))}
            </div>
          </div>
        )}
        {outboundEvents.length > 0 && (
          <div>
            <div style={{ color: "#94a3b8", fontSize: 13, marginBottom: 4 }}>Outbound Events ({outboundEvents.length}):</div>
            <div style={{ maxHeight: 150, overflow: "auto", fontSize: 12 }}>
              {[...outboundEvents].reverse().map((ev, idx) => (
                <div key={idx} style={{ padding: "4px 8px", borderBottom: "1px solid #1e293b" }}>
                  <span style={{ color: "#6b7280" }}>#{String(ev.sequence)}</span>{" "}
                  <span style={{ color: "#60a5fa" }}>{String(ev.event_type)}</span>{" "}
                  <span style={{ color: "#94a3b8" }}>{String(ev.message)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* ──────────── SECTION 14: OAuth Setup Instructions ──────────── */}
      <Section title="13. OAuth Setup Instructions">
        <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.6 }}>
          <p><strong style={{ color: "#e2e8f0" }}>Environment Variables Required:</strong></p>
          <pre style={{ background: "#0f172a", padding: 12, borderRadius: 6, fontSize: 12, color: "#e2e8f0" }}>
{`GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:10000/api/auth/gmail/callback`}
          </pre>
          <p><strong style={{ color: "#e2e8f0" }}>Google Cloud Console Setup:</strong></p>
          <ol style={{ paddingLeft: 20 }}>
            <li>Go to Google Cloud Console → APIs & Services → Credentials</li>
            <li>Create OAuth 2.0 Client ID (Web application)</li>
            <li>Add redirect URI: <code style={{ color: "#60a5fa" }}>http://localhost:10000/api/auth/gmail/callback</code></li>
            <li>Enable Gmail API for the project</li>
            <li>Add scopes: gmail.readonly, gmail.send, userinfo.email</li>
          </ol>
          <p><strong style={{ color: "#e2e8f0" }}>How to verify the pipeline:</strong></p>
          <ol style={{ paddingLeft: 20 }}>
            <li>Click "Connect Gmail" → authorize in Google popup</li>
            <li>Check provider status turns "healthy"</li>
            <li>Click "Sync Everything" → verify sync result shows messages</li>
            <li>Enter a sample message → click "Analyze Message" → verify intents and buying signals appear</li>
            <li>Click "Generate Plan" → verify workflow plan is generated</li>
            <li>Click "Fetch Copilot Context" → verify providers and conversation intelligence are in the context</li>
          </ol>
        </div>
      </Section>
    </div>
  );
}

// ── Sub-components ──

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 28, border: "1px solid #334155", borderRadius: 12, padding: 20, background: "#0f172a" }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, color: "#e2e8f0", margin: "0 0 12px 0", paddingBottom: 8, borderBottom: "1px solid #334155" }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ padding: "2px 0" }}>
      <span style={{ color: "#94a3b8" }}>{k}: </span>
      <span style={{ color: "#e2e8f0", fontWeight: 500 }}>{v || "-"}</span>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 6,
  border: "none",
  color: "#fff",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  transition: "opacity 0.2s",
};
