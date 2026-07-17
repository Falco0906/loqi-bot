"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import Icon from "../../../../components/shared/Icon";
import { getConversation, getConversationEvents, getConversationMessages } from "../../../../lib/api";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  sent: "Sent",
  delivered: "Delivered",
  opened: "Opened",
  replied: "Replied",
  follow_up_pending: "Follow-up Pending",
  follow_up_ready: "Follow-up Ready",
  follow_up_sent: "Follow-up Sent",
  interested: "Interested",
  meeting_booked: "Meeting Booked",
  closed_won: "Closed Won",
  closed_lost: "Closed Lost",
  bounced: "Bounced",
};

const STATUS_COLORS: Record<string, string> = {
  new: "bg-blue-500/20 text-blue-400",
  sent: "bg-surface-high/50 text-on-surface-variant/70",
  delivered: "bg-green-500/20 text-green-400",
  opened: "bg-emerald-500/20 text-emerald-400",
  replied: "bg-amber-500/20 text-amber-400",
  follow_up_pending: "bg-orange-500/20 text-orange-400",
  follow_up_ready: "bg-purple-500/20 text-purple-400",
  follow_up_sent: "bg-violet-500/20 text-violet-400",
  interested: "bg-green-500/20 text-green-400",
  meeting_booked: "bg-teal-500/20 text-teal-400",
  closed_won: "bg-emerald-500/20 text-emerald-400",
  closed_lost: "bg-red-500/20 text-red-400",
  bounced: "bg-red-500/20 text-red-400",
};

const TIMELINE_ICONS: Record<string, string> = {
  campaign_created: "rocket_launch",
  draft_generated: "edit_note",
  email_sent: "mail",
  email_delivered: "check_circle",
  email_opened: "visibility",
  email_bounced: "error",
  reply_received: "forum",
  reply_classified: "auto_awesome",
  follow_up_suggested: "lightbulb",
  follow_up_ready: "timer",
  follow_up_sent: "share",
  meeting_booked: "calendar_today",
  status_changed: "tune",
  summary_updated: "insights",
  note_added: "edit_note",
  closed_won: "star",
  closed_lost: "close",
};

type Params = Promise<{ id: string }>;

export default function ConversationDetailPage({ params }: { params: Params }) {
  const { id } = use(params);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Record<string, unknown> | null>(null);
  const [timeline, setTimeline] = useState<Record<string, unknown>[]>([]);
  const [messages, setMessages] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  useEffect(() => {
    if (!sessionToken || !id) return;
    setLoading(true);
    Promise.all([
      getConversation(sessionToken, id),
      getConversationEvents(sessionToken, id),
      getConversationMessages(sessionToken, id),
    ])
      .then(([convRes, timelineRes, msgsRes]) => {
        if (convRes.ok) setConversation(convRes.conversation);
        if (timelineRes.ok) setTimeline(timelineRes.events || []);
        if (msgsRes.ok) setMessages(msgsRes.messages || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionToken, id]);

  if (loading) {
    return (
      <WorkspaceContainer>
        <div className="flex items-center justify-center h-full">
          <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      </WorkspaceContainer>
    );
  }

  if (!conversation) {
    return (
      <WorkspaceContainer>
        <div className="flex flex-col items-center justify-center h-full text-center">
          <Icon name="error" className="text-3xl text-on-surface-variant/40 mb-3" />
          <p className="text-body-lg text-on-surface-variant/80">Conversation not found</p>
          <Link href="/conversations" className="mt-4 text-sm text-primary hover:underline">
            Back to Conversations
          </Link>
        </div>
      </WorkspaceContainer>
    );
  }

  const status = (conversation.status as string) || "new";
  const summary = conversation.summary as Record<string, unknown> | undefined;
  const participants = conversation.participants as Array<Record<string, unknown>> | undefined;
  const contact = summary?.contact_name as string || participants?.[1]?.name as string || "Contact";

  return (
    <WorkspaceContainer>
      <div className="h-full overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto">
          {/* Header */}
          <div className="mb-6">
            <Link
              href="/conversations"
              className="inline-flex items-center gap-1 text-xs text-on-surface-variant/50 hover:text-on-surface-variant/80 mb-3 transition-colors"
            >
              <Icon name="chevron_right" className="text-sm rotate-180" />
              Back to Conversations
            </Link>
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-container/20 shrink-0">
                <Icon name="forum" className="text-2xl text-primary" />
              </div>
              <div className="min-w-0">
                <h1 className="text-xl font-bold text-on-surface truncate">{contact}</h1>
                <div className="flex items-center gap-3 mt-0.5">
                  {(summary?.company as string) && (
                    <span className="text-sm text-on-surface-variant/70">{summary?.company as string}</span>
                  )}
                  {(summary?.contact_email as string) && (
                    <span className="text-sm text-on-surface-variant/50">{summary?.contact_email as string}</span>
                  )}
                </div>
              </div>
              <span className={`ml-auto shrink-0 px-3 py-1.5 rounded-full text-xs font-medium ${STATUS_COLORS[status] || "bg-surface-high/50 text-on-surface-variant/70"}`}>
                {STATUS_LABELS[status] || status}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main: Timeline + Messages */}
            <div className="lg:col-span-2 space-y-6">
              {/* AI Summary */}
              {(summary?.last_summary as string) && (
                <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Icon name="auto_awesome" className="text-sm text-primary" />
                    <span className="text-xs font-medium text-on-surface-variant/70 uppercase tracking-wider">Summary</span>
                  </div>
                  <p className="text-sm text-on-surface/80 leading-relaxed">{summary?.last_summary as string}</p>
                  {(summary?.interest_level as string) && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-xs text-on-surface-variant/50">Interest:</span>
                      <span className="text-xs font-medium text-on-surface-variant/80 capitalize">{summary?.interest_level as string}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Timeline */}
              <div>
                <h2 className="text-sm font-semibold text-on-surface mb-3">Timeline</h2>
                <div className="space-y-0">
                  {timeline.length === 0 ? (
                    <div className="text-sm text-on-surface-variant/50 py-8 text-center">No timeline events yet.</div>
                  ) : (
                    timeline.map((event, idx) => {
                      const etype = event.event_type as string;
                      const icon = TIMELINE_ICONS[etype] || "more_horiz";
                      const isLast = idx === timeline.length - 1;
                      return (
                        <div key={event.event_id as string} className="flex gap-3">
                          <div className="flex flex-col items-center">
                            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-high/50">
                              <Icon name={icon} className="text-xs text-on-surface-variant/60" />
                            </div>
                            {!isLast && <div className="w-px flex-1 bg-outline-variant/10 min-h-[24px]" />}
                          </div>
                          <div className={`pb-4 ${isLast ? "" : ""}`}>
                            <p className="text-sm text-on-surface/80">{event.title as string}</p>
                            {(event.description as string) && (
                              <p className="text-xs text-on-surface-variant/50 mt-0.5">{event.description as string}</p>
                            )}
                            {(event.timestamp as string) && (
                              <p className="text-[11px] text-on-surface-variant/40 mt-0.5">
                                {new Date(event.timestamp as string).toLocaleString()}
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Messages */}
              <div>
                <h2 className="text-sm font-semibold text-on-surface mb-3">Messages</h2>
                {messages.length === 0 ? (
                  <div className="text-sm text-on-surface-variant/50 py-8 text-center border border-outline-variant/10 rounded-xl">
                    No messages yet.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {messages.map((msg) => {
                      const isInbound = msg.direction === "inbound";
                      return (
                        <div
                          key={msg.message_id as string}
                          className={`rounded-xl border border-outline-variant/10 p-4 ${isInbound ? "bg-primary-container/5 border-l-2 border-l-primary/30" : "bg-charcoal/50 border-l-2 border-l-outline-variant/20"}`}
                        >
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-medium text-on-surface-variant/70">
                              {isInbound ? (msg.from_name as string || msg.from_email as string) : (msg.to_name as string || msg.to_email as string)}
                            </span>
                            <span className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                              {isInbound ? "→ Inbound" : "← Outbound"}
                            </span>
                            {(msg.sent_at as string) && (
                              <span className="text-[10px] text-on-surface-variant/40 ml-auto">
                                {new Date(msg.sent_at as string).toLocaleString()}
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-on-surface whitespace-pre-wrap line-clamp-6">
                            {msg.body_preview as string || (msg.body as string)?.slice(0, 300)}
                          </p>
                          {(msg.body as string || "").length > 300 && (
                            <button className="mt-1 text-xs text-primary hover:underline">Show more</button>
                          )}
                          {!!(msg.classification as Record<string, unknown>)?.category && (
                            <div className="mt-2 flex items-center gap-2">
                              <span className="text-[10px] text-on-surface-variant/40 uppercase">Classified:</span>
                              <span className="text-[11px] font-medium text-on-surface-variant/70 capitalize">
                                {(msg.classification as Record<string, unknown>)?.category as string}
                              </span>
                              <span className="text-[10px] text-on-surface-variant/40">
                                ({(Math.round(((msg.classification as Record<string, unknown>).confidence as number || 0) * 100))}%)
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Sidebar: Details + Actions */}
            <div className="space-y-4">
              {/* Details Card */}
              <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4">
                <h3 className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider mb-3">Details</h3>
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-xs text-on-surface-variant/50">Subject</span>
                    <span className="text-xs text-on-surface/70 text-right max-w-[180px] truncate">{conversation.subject as string || "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-on-surface-variant/50">Provider</span>
                    <span className="text-xs text-on-surface/70">{conversation.provider_type as string || "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-on-surface-variant/50">Messages</span>
                    <span className="text-xs text-on-surface/70">{conversation.message_count as number || 0}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-on-surface-variant/50">Campaign</span>
                    <span className="text-xs text-on-surface/70 truncate max-w-[160px]">{conversation.campaign_id as string || "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-on-surface-variant/50">Created</span>
                    <span className="text-xs text-on-surface/70">{conversation.created_at ? new Date(conversation.created_at as string).toLocaleDateString() : "—"}</span>
                  </div>
                </div>
              </div>

              {/* Participants Card */}
              {participants && participants.length > 0 && (
                <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4">
                  <h3 className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider mb-3">Participants</h3>
                  <div className="space-y-2">
                    {participants.map((p, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-high/50">
                          <span className="text-[10px] font-medium text-on-surface-variant/70">
                            {(p.name as string)?.[0] || (p.email as string)?.[0] || "?"}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs text-on-surface/70 truncate">{p.name as string || p.email as string}</p>
                          <p className="text-[10px] text-on-surface-variant/50">{p.role as string || ""}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggested Actions */}
              <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4">
                <h3 className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider mb-3">Suggested Actions</h3>
                <div className="space-y-2">
                  <button
                    disabled
                    className="w-full rounded-lg border border-outline-variant/10 px-3 py-2 text-xs text-on-surface-variant/50 text-left hover:bg-surface-high/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Coming in a future phase"
                  >
                    <div className="flex items-center gap-2">
                      <Icon name="share" className="text-sm" />
                      <span>Send Follow-up</span>
                    </div>
                  </button>
                  <button
                    disabled
                    className="w-full rounded-lg border border-outline-variant/10 px-3 py-2 text-xs text-on-surface-variant/50 text-left hover:bg-surface-high/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Coming in a future phase"
                  >
                    <div className="flex items-center gap-2">
                      <Icon name="auto_awesome" className="text-sm" />
                      <span>Generate Reply</span>
                    </div>
                  </button>
                  <button
                    disabled
                    className="w-full rounded-lg border border-outline-variant/10 px-3 py-2 text-xs text-on-surface-variant/50 text-left hover:bg-surface-high/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Coming in a future phase"
                  >
                    <div className="flex items-center gap-2">
                      <Icon name="calendar_today" className="text-sm" />
                      <span>Schedule Meeting</span>
                    </div>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </WorkspaceContainer>
  );
}
