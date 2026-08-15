"use client";

import { useEffect, useState, use, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import { toast } from "../../../../components/shared/Toast";
import {
  getConversation,
  getConversationEvents,
  getConversationMessages,
  getConversationReasoning,
  generateConversationReply,
  sendConversationReply,
  sendConversationFollowUp,
} from "../../../../lib/api";
import {
  classLabel,
  classTone,
  classificationOf,
  relativeTime,
  shortTime,
  statusLabel,
} from "../../../../lib/conversation-presentation";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

type Params = Promise<{ id: string }>;

const str = (v: unknown) => (v == null ? "" : String(v));

type WorkspaceMessage = { name: string; direction: string; text: string; time: string };
type WorkspaceTimelineItem = { time: string; title: string; description: string };

export default function ConversationWorkspacePage({ params }: { params: Params }) {
  const { id } = use(params);
  const router = useRouter();

  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Record<string, unknown> | null>(null);
  const [timeline, setTimeline] = useState<WorkspaceTimelineItem[]>([]);
  const [messages, setMessages] = useState<WorkspaceMessage[]>([]);
  const [reasoning, setReasoning] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reply, setReply] = useState("");
  const [generatingReply, setGeneratingReply] = useState(false);
  const [sending, setSending] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [testRecipient, setTestRecipient] = useState("");

  const testRecipientEnabled =
    process.env.NEXT_PUBLIC_DEV_MODE === "true" || process.env.NODE_ENV === "development";

  useEffect(() => {
    try {
      setSessionToken(localStorage.getItem(ACTIVE_SESSION_KEY));
    } catch {
      setSessionToken(null);
    }
  }, []);

  /* Load the real conversation: details, events, messages, reasoning */
  const load = useCallback(async () => {
    if (!sessionToken || !id) return;
    setLoading(true);
    setError(null);
    try {
      const [convRes, eventsRes, msgsRes, reasonRes] = await Promise.all([
        getConversation(sessionToken, id),
        getConversationEvents(sessionToken, id),
        getConversationMessages(sessionToken, id),
        getConversationReasoning(sessionToken, id),
      ]);

      if (convRes.ok && convRes.conversation) {
        setConversation(convRes.conversation);
      } else {
        setError("Conversation not found");
      }

      setTimeline(
        (eventsRes.ok ? eventsRes.events : [])
          .slice(-10)
          .map((e: Record<string, unknown>) => ({
            time: str(e.timestamp || ""),
            title: str(e.title || e.description || e.event_type || ""),
            description: str(e.description || ""),
          })),
      );

      setMessages(
        (msgsRes.ok ? msgsRes.messages : []).map((m: Record<string, unknown>) => ({
          name: m.direction === "inbound"
            ? str(m.from_name || m.from_email || "Contact")
            : str(m.to_name || m.to_email || "You"),
          direction: str(m.direction || "outbound"),
          text: str(m.body_preview || (m.body as string)?.slice(0, 500) || ""),
          time: str(m.sent_at || ""),
        })),
      );

      setReasoning(
        reasonRes.ok ? (reasonRes.reasoning as Record<string, unknown> | null) : null,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load conversation");
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [sessionToken, id]);

  useEffect(() => {
    void load();
  }, [load]);

  /* Primary action mode from the actual conversation state/history:
     - follow_up: no inbound reply yet and a follow-up is due → FOLLOW-UP
     - follow_up_sent: follow-up was already sent → nothing to send
     - reply: there is an inbound message from the contact → REPLY */
  const conversationStatus = str(conversation?.status);
  const hasInbound = messages.some((m) => m.direction === "inbound");
  const followUpDue =
    conversationStatus === "follow_up_pending" || conversationStatus === "follow_up_ready";
  const mode: "follow_up" | "follow_up_sent" | "reply" = followUpDue && !hasInbound
    ? "follow_up"
    : conversationStatus === "follow_up_sent"
      ? "follow_up_sent"
      : "reply";

  /* Auto-generate the recommended reply / follow-up once the workspace opens */
  useEffect(() => {
    if (!sessionToken || !id || !loaded) return;
    let cancelled = false;
    setGeneratingReply(true);
    (async () => {
      try {
        const res = await generateConversationReply(sessionToken, id, {
          styles: ["professional"],
          variant_count: 1,
          follow_up: mode === "follow_up",
        });
        const variants = (
          res.generation as { variants?: Array<{ drafts?: Array<{ content?: string }> }> } | null
        )?.variants;
        const content = variants?.[0]?.drafts?.[0]?.content || "";
        if (!cancelled) setReply(content);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to generate recommended reply");
        }
      } finally {
        if (!cancelled) setGeneratingReply(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionToken, id, loaded, mode]);

  const handleRefine = useCallback(async () => {
    if (!sessionToken || !id || generatingReply) return;
    const instruction = window.prompt("What would you like to change about the reply?");
    if (instruction === null || !instruction.trim()) return;
    setGeneratingReply(true);
    try {
      const res = await generateConversationReply(sessionToken, id, {
        styles: ["professional"],
        variant_count: 1,
        instruction: instruction.trim(),
        follow_up: mode === "follow_up",
      });
      const variants = (
        res.generation as { variants?: Array<{ drafts?: Array<{ content?: string }> }> } | null
      )?.variants;
      const content = variants?.[0]?.drafts?.[0]?.content || "";
      if (!content) {
        toast("error", "No reply generated for that instruction.");
        return;
      }
      setReply(content);
      toast("success", "Recommended reply updated");
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to refine reply");
    } finally {
      setGeneratingReply(false);
    }
  }, [sessionToken, id, generatingReply, mode]);

  const handleSend = useCallback(async () => {
    if (!sessionToken || !id || sending) return;
    const body = reply.trim();
    if (!body) {
      toast("error", "No reply to send yet — wait for the AI recommendation.");
      return;
    }
    setSending(true);
    try {
      const testOptions = testRecipient.trim()
        ? { test_recipient: testRecipient.trim(), test_recipient_name: "Test Recipient" }
        : {};
      if (mode === "follow_up") {
        await sendConversationFollowUp(sessionToken, id, { body, ...testOptions });
        toast("success", "Follow-up sent");
      } else {
        await sendConversationReply(sessionToken, id, { body, ...testOptions });
        toast("success", "Reply sent");
      }
      router.push("/inbox");
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to send");
    } finally {
      setSending(false);
    }
  }, [sessionToken, id, reply, sending, mode, router, testRecipient]);

  /* ── Derived presentation (all real data) ── */

  const rawSummary = (conversation?.summary as Record<string, unknown> | undefined) || {};
  const participants = Array.isArray(conversation?.participants)
    ? (conversation.participants as Record<string, unknown>[])
    : [];
  const contact =
    participants.find((p) => str(p.role).toLowerCase() === "contact") ||
    participants[1] ||
    participants[0] ||
    {};
  const metadata = (conversation?.metadata as Record<string, unknown> | undefined) || {};

  const contactName =
    str(contact.name || contact.email || rawSummary.contact_name) || "Contact";
  const contactEmail = str(contact.email || rawSummary.contact_email);
  const company = str(conversation?.company_name || rawSummary.company || contact.company);
  const subject = str(conversation?.subject);
  const messageCount = Number(conversation?.message_count || 0);
  const lastActivity = str(conversation?.last_activity_at || "");
  const classification = classificationOf({
    classification: str(metadata.last_reply_category),
    status: str(conversation?.status),
  });
  const statusText = statusLabel(str(conversation?.status));

  const reasoningDecision = reasoning?.decision as Record<string, unknown> | undefined;
  const reasoningPriority = reasoning?.priority as Record<string, unknown> | undefined;
  const reasoningRisk = reasoning?.risk as Record<string, unknown> | undefined;
  const reasoningConfidence = reasoning?.confidence as Record<string, unknown> | undefined;
  const reasoningGoal = reasoning?.goal as Record<string, unknown> | undefined;

  /* ── States ── */

  if (loading) {
    return (
      <WorkspaceContainer>
        <div className="flex h-full flex-col px-6 pt-6">
          <div className="h-3 w-24 bg-surface-high/50 rounded animate-skeleton-pulse" />
          <div className="mt-4 h-6 w-64 bg-surface-high/50 rounded animate-skeleton-pulse" />
          <div className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
            <div className="lg:col-span-2 space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-16 bg-surface-high/40 rounded-lg animate-skeleton-pulse" />
              ))}
            </div>
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-24 bg-surface-high/40 rounded-lg animate-skeleton-pulse" />
              ))}
            </div>
          </div>
        </div>
      </WorkspaceContainer>
    );
  }

  if (error && !conversation) {
    return (
      <WorkspaceContainer>
        <div className="flex flex-col items-center justify-center h-full text-center px-6">
          <p className="text-lg text-error mb-4">{error}</p>
          <button
            onClick={() => void load()}
            className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Retry
          </button>
          <Link href="/inbox" className="mt-4 text-sm text-primary hover:underline">
            Back to Inbox
          </Link>
        </div>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <div className="flex h-full flex-col min-h-0 animate-fade-in">

        {/* Header */}
        <header className="px-6 pt-5 pb-4 border-b border-outline-variant/10 shrink-0">
          <Link
            href="/inbox"
            className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant/50 hover:text-primary transition-colors mb-3"
          >
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to Inbox
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                {classification && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider ${classTone(classification)}`}
                  >
                    {classLabel(classification)}
                  </span>
                )}
                {statusText &&
                  statusText.toLowerCase() !== classLabel(classification).toLowerCase() && (
                    <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40">
                      {statusText}
                    </span>
                  )}
              </div>
              <h1 className="font-serif text-lg text-on-surface font-normal mt-1.5 truncate">
                {contactName}
              </h1>
              <p className="text-xs text-on-surface-variant/50 truncate">
                {[company, contactEmail].filter(Boolean).join(" · ")}
              </p>
              {subject && (
                <p className="text-xs text-on-surface-variant/40 truncate mt-0.5">{subject}</p>
              )}
            </div>
            <div className="shrink-0 text-right">
              <p className="text-[11px] text-on-surface-variant/40 tabular-nums">
                {messageCount} message{messageCount !== 1 ? "s" : ""}
              </p>
              {lastActivity && (
                <p className="text-[11px] text-on-surface-variant/40 tabular-nums mt-0.5">
                  {relativeTime(lastActivity)}
                </p>
              )}
            </div>
          </div>
        </header>

        {/* Body: conversation thread | AI insight + recommended reply */}
        <div className="flex-1 overflow-y-auto">
          {error && conversation && (
            <div className="px-6 pt-4">
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2">
                <p className="text-[11px] text-red-400">{error}</p>
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 px-6 py-5 max-w-6xl mx-auto">
            <div className="lg:col-span-2 space-y-6">
              {/* Conversation (real messages) */}
              <section>
                <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2.5">
                  Conversation
                </span>
                {messages.length === 0 ? (
                  <p className="text-sm text-on-surface-variant/40 italic">No messages yet.</p>
                ) : (
                  <div className="space-y-2.5">
                    {messages.map((m, i) => (
                      <div
                        key={i}
                        className={`rounded-lg border px-3.5 py-2.5 ${
                          m.direction === "inbound"
                            ? "bg-primary-container/5 border-l-2 border-l-primary/30"
                            : "bg-surface-container/50 border-l-2 border-l-outline-variant/20"
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium text-on-surface/90">{m.name}</span>
                          <span className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                            {m.direction === "inbound" ? "Inbound" : "Outbound"}
                          </span>
                          {m.time && (
                            <span className="text-[10px] text-on-surface-variant/40 ml-auto">
                              {shortTime(m.time)}
                            </span>
                          )}
                        </div>
                        <p className="text-[13px] text-on-surface/80 leading-relaxed whitespace-pre-wrap">
                          {m.text}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Timeline (recent events) */}
              {timeline.length > 0 && (
                <section>
                  <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2.5">
                    Timeline
                  </span>
                  <div className="space-y-2">
                    {timeline.map((t, i) => (
                      <div key={i} className="flex items-baseline gap-2 text-xs">
                        <span className="text-on-surface-variant/40 shrink-0 w-20 text-right tabular-nums">
                          {shortTime(t.time)}
                        </span>
                        <span className="text-on-surface/80 truncate">{t.title}</span>
                        {t.description && t.description !== t.title && (
                          <span className="text-on-surface-variant/40 truncate">
                            — {t.description}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>

            <div className="space-y-6">
              {/* AI reasoning (real intelligence) */}
              <section>
                <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2.5">
                  AI Reasoning
                </span>
                {str(rawSummary.last_summary) && (
                  <p className="text-[13px] text-on-surface-variant/80 leading-relaxed mb-3">
                    {str(rawSummary.last_summary)}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {str(reasoningDecision?.type) && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Decision
                      </span>
                      <span className="text-xs text-on-surface capitalize">
                        {str(reasoningDecision?.type).replace(/_/g, " ")}
                      </span>
                    </div>
                  )}
                  {str(reasoningDecision?.priority) && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Priority
                      </span>
                      <span className="text-xs text-on-surface capitalize">
                        {str(reasoningDecision?.priority)}
                      </span>
                    </div>
                  )}
                  {str(reasoningDecision?.risk) && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Risk
                      </span>
                      <span className="text-xs text-on-surface capitalize">
                        {str(reasoningDecision?.risk)}
                      </span>
                    </div>
                  )}
                  {reasoningConfidence?.["overall"] !== undefined && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Confidence
                      </span>
                      <span className="text-xs text-on-surface">
                        {Math.round(Number(reasoningConfidence.overall) * 100)}%
                      </span>
                    </div>
                  )}
                  {str(reasoningGoal?.primary) && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Goal
                      </span>
                      <span className="text-xs text-on-surface capitalize">
                        {str(reasoningGoal?.primary).replace(/_/g, " ")}
                      </span>
                    </div>
                  )}
                  {str(reasoningPriority?.level) && (
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 block">
                        Urgency
                      </span>
                      <span className="text-xs text-on-surface capitalize">
                        {str(reasoningPriority?.level)}
                      </span>
                    </div>
                  )}
                </div>
                {Array.isArray(reasoningDecision?.evidence) &&
                  (reasoningDecision.evidence as unknown[]).length > 0 && (
                    <ul className="mt-3 space-y-1.5">
                      {(reasoningDecision.evidence as unknown[]).slice(0, 4).map((e, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs text-on-surface-variant/70">
                          <span className="material-symbols-outlined text-[14px] text-primary mt-px shrink-0">
                            check_circle
                          </span>
                          {str(e)}
                        </li>
                      ))}
                    </ul>
                  )}
                {!reasoning && !rawSummary.last_summary && (
                  <p className="text-sm text-on-surface-variant/40 italic">
                    No reasoning signal available yet.
                  </p>
                )}
              </section>

              {/* Recommended reply / follow-up (editable) */}
              <section>
                <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2.5">
                  {mode === "reply" ? "Recommended Reply" : "Recommended Follow-up"}
                </span>
                <div className="relative">
                  <textarea
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    disabled={generatingReply}
                    rows={7}
                    placeholder={
                      generatingReply
                        ? "Generating…"
                        : mode === "reply"
                          ? "AI recommended reply appears here."
                          : "AI recommended follow-up appears here."
                    }
                    className="w-full bg-surface-container/50 border border-outline-variant/10 rounded-lg p-3 text-[13px] text-on-surface leading-relaxed resize-none focus:outline-none focus:border-primary/30 transition-colors disabled:opacity-60"
                  />
                  {generatingReply && (
                    <div className="absolute inset-0 flex items-center justify-center bg-surface-lowest/60 rounded-lg">
                      <div className="flex items-center gap-2 text-xs text-on-surface-variant/70">
                        <span className="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        {mode === "reply"
                          ? "Generating recommended reply…"
                          : "Generating recommended follow-up…"}
                      </div>
                    </div>
                  )}
                </div>
                {mode === "follow_up_sent" ? (
                  <p className="mt-3 text-xs text-on-surface-variant/50">
                    Follow-up already sent — awaiting a response.
                  </p>
                ) : (
                  <div className="mt-3">
                    {testRecipientEnabled && (
                      <label className="mb-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 px-2.5 py-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-warning">Test recipient</span>
                        <input
                          type="email"
                          value={testRecipient}
                          onChange={(e) => setTestRecipient(e.target.value)}
                          placeholder="operator-second@gmail.com"
                          className="min-w-0 flex-1 bg-transparent text-xs text-on-surface outline-none placeholder:text-on-surface-variant/40"
                        />
                      </label>
                    )}
                    {testRecipient.trim() ? (
                      <span className="mb-3 inline-flex items-center gap-1.5 rounded-lg border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs font-bold text-warning">
                        TEST RECIPIENT
                      </span>
                    ) : null}
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => void handleRefine()}
                        disabled={sending || generatingReply}
                        className="border border-outline-variant/20 text-primary text-sm font-medium px-5 py-2.5 rounded-full hover:bg-surface-container active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {generatingReply ? "Refining…" : "Refine"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleSend()}
                        disabled={sending || generatingReply || !reply.trim()}
                        className="flex-1 bg-primary text-on-primary text-sm font-medium py-2.5 rounded-full hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {sending
                          ? "Sending…"
                          : mode === "reply"
                            ? "Approve & Send"
                            : "Send Follow-up"}
                      </button>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </div>
        </div>
      </div>
    </WorkspaceContainer>
  );
}
