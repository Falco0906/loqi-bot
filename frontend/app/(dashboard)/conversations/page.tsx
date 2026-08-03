"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import Icon from "../../../components/shared/Icon";
import { listConversations } from "../../../lib/api";
import { useTellLoqi } from "../../../hooks/useTellLoqi";

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

export default function ConversationsPage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const tellLoqi = useTellLoqi("Conversations", { count: conversations.length });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  useEffect(() => {
    if (!sessionToken) return;
    setLoading(true);
    listConversations(sessionToken)
      .then((res) => {
        if (res.ok) setConversations(res.conversations || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionToken]);

  return (
    <WorkspaceContainer>
      <div className="h-full overflow-y-auto px-6 py-6">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Icon name="forum" className="text-primary text-xl" />
            </div>
            <div>
              <h1 className="text-headline-md text-on-surface font-bold">Conversations</h1>
              <p className="text-body-md text-on-surface-variant/60">
                {conversations.length} conversation{conversations.length !== 1 ? "s" : ""}
              </p>
            </div>
          </div>

          {loading ? (
            <div className="space-y-3 animate-fade-in">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="flex items-center gap-4 rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4 animate-skeleton-pulse"
                  style={{ animationDelay: `${i * 0.05}s` }}
                >
                  <div className="h-10 w-10 rounded-lg bg-surface-high/50 shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-48 bg-surface-high/50 rounded" />
                    <div className="h-3 w-32 bg-surface-high/50 rounded" />
                  </div>
                  <div className="h-6 w-20 bg-surface-high/50 rounded-full" />
                </div>
              ))}
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <Icon name="forum" className="text-3xl" />
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No conversations yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                Conversations appear here after you send emails from Campaigns.
              </p>
              <Link
                href="/campaigns"
                className="mt-6 inline-flex items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary hover:brightness-110 active:scale-[0.97] transition-all"
              >
                View Campaigns
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {conversations.map((c) => {
                const status = (c.status as string) || "new";
                const summary = c.summary as Record<string, unknown> | undefined;
                const lastActivity = c.last_activity_at as string | undefined;
                return (
                  <Link
                    key={c.conversation_id as string}
                    href={`/conversations/${c.conversation_id}`}
                    className="flex items-center gap-4 rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4 hover:bg-charcoal/80 hover:border-outline-variant/30 transition-all duration-150 group"
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-container/20 shrink-0">
                      <Icon name="forum" className="text-lg text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-on-surface truncate">
                          {summary?.contact_name as string || c.subject as string || "Untitled"}
                        </span>
                        {(summary?.company as string) && (
                          <span className="text-xs text-on-surface-variant/50 truncate">
                            {summary?.company as string}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs text-on-surface-variant/50">
                          {summary?.contact_email as string || "—"}
                        </span>
                        {(c.message_count as number) > 0 && (
                          <span className="text-xs text-on-surface-variant/40">
                            {c.message_count as number} message{(c.message_count as number) !== 1 ? "s" : ""}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className={`px-2.5 py-1 rounded-full text-[11px] font-medium ${STATUS_COLORS[status] || "bg-surface-high/50 text-on-surface-variant/70"}`}>
                        {STATUS_LABELS[status] || status}
                      </span>
                      {lastActivity && (
                        <span className="text-[11px] text-on-surface-variant/40 hidden sm:block">
                          {new Date(lastActivity).toLocaleDateString()}
                        </span>
                      )}
                      <Icon name="chevron_right" className="text-lg text-on-surface-variant/20 group-hover:text-on-surface-variant/50 transition-colors" />
                    </div>
                  </Link>
                );
              })}
            </div>
          )}

          {/* Tell Loqi */}
          <div className="mt-16 pt-8 border-t border-outline-variant/20">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="Which conversations need follow-up?"
                  rows={1}
                  value={tellLoqi.text}
                  onChange={(e) => tellLoqi.setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void tellLoqi.submit();
                    }
                  }}
                />
                <button
                  type="button"
                  disabled={tellLoqi.sending || !tellLoqi.text.trim()}
                  onClick={() => void tellLoqi.submit()}
                  className="bg-primary text-on-primary w-10 h-10 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0 disabled:opacity-40"
                >
                  <span className="material-symbols-outlined text-sm">arrow_upward</span>
                </button>
              </div>
            </div>
            <div className="mt-4 flex justify-center gap-3 overflow-x-auto no-scrollbar">
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Which conversations need follow-up attention right now?")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                NEEDS FOLLOW-UP
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Summarize all replied conversations and suggest next steps.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                SUMMARIZE REPLIES
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Identify conversations at risk of going cold and recommend re-engagement.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                AT RISK
              </button>
            </div>
          </div>
        </div>
      </div>
    </WorkspaceContainer>
  );
}
