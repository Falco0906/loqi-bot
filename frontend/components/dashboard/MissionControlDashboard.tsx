"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSession, getCampaignSummary } from "../../lib/api";
import type { LoqiMessage, LoqiSessionSummary } from "../../lib/types";
import Icon from "../shared/Icon";
import { usePageContext } from "../../hooks/usePageContext";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";
const SESSION_INDEX_KEY = "loqi_session_index";

type StoredSession = {
  token: string;
  title: string;
  updatedAt: string;
};

function readStoredSessions(): StoredSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSION_INDEX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as StoredSession[];
    return Array.isArray(parsed) ? parsed.filter((s) => s?.token) : [];
  } catch {
    return [];
  }
}

function getActiveToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(ACTIVE_SESSION_KEY);
  } catch {
    return null;
  }
}

function countByType(messages: LoqiMessage[], type: string): number {
  return messages.filter((m) => m.type === type).length;
}

function formatTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function MissionControlDashboard() {
  const [session, setSession] = useState<LoqiSessionSummary | null>(null);
  const [sessions, setSessions] = useState<StoredSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCampaigns, setActiveCampaigns] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    const stored = readStoredSessions();
    setSessions(stored);

    const token = getActiveToken() || stored[0]?.token;
    if (!token) {
      setLoading(false);
      return;
    }

    Promise.all([
      getSession(token).catch(() => null),
      getCampaignSummary(token).catch(() => ({ ok: false, campaigns: [] })),
    ]).then(([sessionData, campaignData]) => {
      if (sessionData) setSession(sessionData);
      if (campaignData?.ok && Array.isArray(campaignData.campaigns)) {
        setActiveCampaigns(
          campaignData.campaigns.filter((c) => c.status !== "archived" && c.status !== "completed"),
        );
      }
      setLoading(false);
    });
  }, []);

  const messages = session?.messages ?? [];
  const workflowSessions = session?.workflow_sessions ?? [];
  const displayName = session?.display_name ?? "there";

  const leadListCount = countByType(messages, "lead_list");
  const draftCount = countByType(messages, "draft_preview");
  const userMessages = messages.filter((m) => m.role === "user");
  const recentMessages = messages.slice(-10).reverse();

  const hasActiveWorkflow = workflowSessions.length > 0;
  const hasMessages = messages.length > 0;

  usePageContext("Mission Control", {
    active_campaigns: activeCampaigns.length,
    recent_activity: userMessages.length > 0 ? "has_activity" : "no_activity",
    pending_drafts: draftCount,
    has_active_workflow: hasActiveWorkflow,
  });

  return (
    <>
      {/* Background atmospheric effect */}
      <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
        <div className="absolute top-1/4 -left-20 w-96 h-96 bg-primary/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-1/4 -right-20 w-96 h-96 bg-secondary/5 blur-[120px] rounded-full" />
      </div>

      <div className="max-w-[1400px] mx-auto px-6 pb-20">
        {/* Greeting */}
        <section className="mb-8">
          <h1 className="text-headline-xl text-on-surface">
            Good morning, {displayName}.
          </h1>
          <p className="mt-2 text-body-lg text-on-surface-variant max-w-2xl">
            {hasMessages
              ? "While you were away, I found a few things worth your attention. I've prepared a brief of the most critical signals detected overnight."
              : "I'm ready to help you find leads and craft outreach. Start by telling me what you're selling and who you want to reach."}
          </p>
        </section>

        <div className="bento-grid">
          {/* AI Morning Brief */}
          <div className="col-span-12 lg:col-span-8">
            <MorningBriefSection
              hasData={hasActiveWorkflow}
              leadListCount={leadListCount}
              draftCount={draftCount}
              campaignCount={workflowSessions.length}
              userMessageCount={userMessages.length}
            />
          </div>

          {/* AI Activity Feed */}
          <div className="col-span-12 lg:col-span-4 row-span-2">
            <ActivityFeedSection
              messages={recentMessages}
              hasData={hasMessages}
            />
          </div>

          {/* Active Campaigns */}
          <div className="col-span-12 lg:col-span-4">
            <CampaignSummarySection
              workflowSessions={workflowSessions}
              storedSessions={sessions}
              hasData={hasActiveWorkflow}
            />
          </div>

          {/* Continue Working */}
          <div className="col-span-12 lg:col-span-4">
            <ContinueWorkingSection campaigns={activeCampaigns} />
          </div>

          {/* Quick Actions */}
          <div className="col-span-12 lg:col-span-8">
            <QuickActionsSection />
          </div>
        </div>
      </div>
    </>
  );
}

/* ─── AI Morning Brief ─── */
function MorningBriefSection({
  hasData,
  leadListCount,
  draftCount,
  campaignCount,
  userMessageCount,
}: {
  hasData: boolean;
  leadListCount: number;
  draftCount: number;
  campaignCount: number;
  userMessageCount: number;
}) {
  if (!hasData) {
    return (
      <div className="relative overflow-hidden rounded-3xl glass-panel p-8 h-full border border-outline-variant/20">
        <div className="flex flex-col h-full">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center text-primary">
              <Icon name="auto_awesome" />
            </div>
            <h3 className="text-headline-md">AI Morning Brief</h3>
          </div>
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center max-w-sm">
              <div className="text-5xl mb-4 opacity-30">🌅</div>
              <p className="text-body-lg text-on-surface-variant/60">
                No campaigns running yet.
              </p>
              <p className="mt-2 text-body-md text-on-surface-variant/40">
                Start by telling Loqi what you sell and who you want to reach — the morning brief
                will show your daily activity here.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-3xl glass-panel p-8 h-full border border-primary/20 group">
      <div className="absolute -right-20 -top-20 w-80 h-80 bg-primary/10 blur-[100px] rounded-full group-hover:bg-primary/20 transition-all duration-700" />
      <div className="relative z-10 flex flex-col h-full">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center text-primary">
            <Icon name="auto_awesome" />
          </div>
          <h3 className="text-headline-md">AI Morning Brief</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <BriefStat value={leadListCount} label="Lead Searches Run" color="text-secondary" />
          <BriefStat value={draftCount} label="Drafts Generated" color="text-tertiary" />
          <BriefStat value={campaignCount} label="Active Campaigns" color="text-primary" />
        </div>

        <div className="mt-auto">
          <Link
            href="/discovery"
            className="inline-flex items-center gap-3 bg-white text-surface px-8 py-4 rounded-2xl font-bold hover:scale-[1.02] active:scale-[0.98] transition-all"
          >
            Review My Brief
            <Icon name="arrow_forward" />
          </Link>
        </div>
      </div>
    </div>
  );
}

function BriefStat({ value, label, color }: { value: number; label: string; color: string }) {
  return (
    <div className="p-6 rounded-2xl bg-surface-high/30 border border-outline-variant/10">
      <p className={`font-bold text-headline-lg mb-1 ${color}`}>{value}</p>
      <p className="text-label-md text-on-surface-variant uppercase tracking-wider">{label}</p>
    </div>
  );
}

/* ─── Activity Feed ─── */
function ActivityFeedSection({
  messages,
  hasData,
}: {
  messages: LoqiMessage[];
  hasData: boolean;
}) {
  return (
    <div className="glass-panel rounded-3xl p-8 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-headline-md">Loqi Activity</h3>
        <Icon name="more_horiz" className="text-on-surface-variant" />
      </div>

      {!hasData ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-body-lg text-on-surface-variant/40">No recent activity</p>
            <p className="mt-1 text-body-md text-on-surface-variant/30">
              Activity from your campaigns will appear here.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 space-y-6 overflow-y-auto pr-2">
          {messages.slice(0, 8).map((msg) => (
            <ActivityItem key={msg.id} message={msg} />
          ))}
        </div>
      )}

      {hasData && (
        <Link
          href="/discovery"
          className="mt-6 text-primary text-label-md flex items-center gap-2 hover:translate-x-1 transition-transform"
        >
          View Full History
          <Icon name="chevron_right" className="text-sm" />
        </Link>
      )}
    </div>
  );
}

function ActivityItem({ message }: { message: LoqiMessage }) {
  const isUser = message.role === "user";
  const isLeadList = message.type === "lead_list";
  const isDraft = message.type === "draft_preview";
  const isStatus = message.type === "status";
  const time = formatTime(message.created_at);

  let dotColor = "bg-primary";
  let label = "System";

  if (isUser) {
    dotColor = "bg-tertiary";
    label = "You";
  } else if (isDraft) {
    dotColor = "bg-secondary";
    label = "Draft";
  } else if (isLeadList) {
    dotColor = "bg-primary";
    label = "Discovery";
  } else if (isStatus) {
    dotColor = "bg-on-surface-variant/40";
    label = "Status";
  }

  const preview =
    message.text.length > 100 ? message.text.slice(0, 100) + "..." : message.text;

  return (
    <div className="relative pl-8 border-l border-outline-variant/20">
      <div className={`absolute -left-[5px] top-0 w-2.5 h-2.5 rounded-full ${dotColor} border-4 border-obsidian`} />
      {time ? (
        <p className="text-[10px] uppercase font-bold text-on-surface-variant mb-1">{time}</p>
      ) : null}
      <p className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 mb-1">{label}</p>
      <p className="text-body-md text-on-surface">{preview}</p>
    </div>
  );
}

/* ─── Campaign Summary ─── */
function CampaignSummarySection({
  workflowSessions,
  storedSessions,
  hasData,
}: {
  workflowSessions: LoqiSessionSummary["workflow_sessions"];
  storedSessions: StoredSession[];
  hasData: boolean;
}) {
  return (
    <div className="glass-panel rounded-3xl p-8">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-headline-md">Active Campaigns</h3>
        <span className="text-primary text-label-md">{storedSessions.length} Total</span>
      </div>

      {!hasData ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center text-primary mb-4">
            <Icon name="rocket_launch" className="text-3xl" />
          </div>
          <p className="text-body-lg text-on-surface-variant/60">No campaigns yet</p>
          <p className="mt-1 text-body-md text-on-surface-variant/40">
            Start by describing your service and target audience.
          </p>
          <Link
            href="/discovery"
            className="mt-4 inline-flex items-center gap-2 text-primary text-label-md font-semibold hover:underline"
          >
            Launch your first campaign
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
          {workflowSessions.slice(0, 5).map((ws) => {
            const title = ws.title || getSessionTitle(ws.id);
            const recent = timeAgo(ws.updated_at);
            return (
              <div key={ws.id} className="space-y-2">
                <div className="flex justify-between items-end">
                  <p className="text-body-md font-bold truncate pr-2">{title}</p>
                  <p className="text-[10px] text-on-surface-variant shrink-0">{recent}</p>
                </div>
                <div className="w-full bg-surface-high h-1.5 rounded-full overflow-hidden">
                  <div className="bg-primary h-full w-[60%] rounded-full" />
                </div>
                <div className="flex justify-between mt-1">
                  <div className="text-[10px] text-on-surface-variant uppercase font-bold">
                    Active
                  </div>
                  <Link
                    href="/discovery"
                    className="text-primary font-bold text-[10px] uppercase hover:underline"
                  >
                    Continue
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function getSessionTitle(id: string) {
  const short = id.slice(0, 8);
  return `Campaign ${short}`;
}

/* ─── Continue Working ─── */
function ContinueWorkingSection({
  campaigns,
}: {
  campaigns: Array<Record<string, unknown>>;
}) {
  const statusLabels: Record<string, string> = {
    planning: "Strategy awaiting approval",
    ready: "Ready to start drafting",
    generating: "Drafts being generated",
    draft_review: "drafts pending review",
    ready_to_send: "Ready to send",
  };

  const statusColors: Record<string, string> = {
    planning: "bg-warning",
    ready: "bg-primary",
    generating: "bg-secondary",
    draft_review: "bg-primary-container",
    ready_to_send: "bg-success",
  };

  return (
    <div className="glass-panel rounded-3xl p-8 flex flex-col h-full bg-surface-high/20">
      <div className="flex items-center gap-3 mb-4">
        <Icon name="edit_note" className="text-tertiary" />
        <h3 className="text-headline-md">Continue Working</h3>
      </div>

      {campaigns.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center">
          <div className="w-14 h-14 rounded-2xl bg-surface-highest/40 flex items-center justify-center text-on-surface-variant/40 mb-4">
            <Icon name="edit_note" className="text-3xl" />
          </div>
          <p className="text-body-lg text-on-surface-variant/60">Nothing in progress</p>
          <p className="mt-1 text-body-md text-on-surface-variant/40">
            Your active campaigns will appear here.
          </p>
        </div>
      ) : (
        <div className="flex-1 space-y-3 overflow-y-auto">
          {campaigns.map((c) => {
            const id = c.id as string;
            const name = c.name as string;
            const status = c.status as string;
            const pd = c.pending_drafts as number;
            const label =
              status === "draft_review"
                ? `${pd} ${statusLabels[status] || status}`
                : (statusLabels[status] || status);
            const dot = statusColors[status] || "bg-outline-variant";
            return (
              <Link
                key={id}
                href={`/campaigns/${id}`}
                className="flex items-center gap-3 p-3 rounded-xl bg-surface-lowest border border-outline-variant/10 hover:border-primary/20 transition-all group"
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-label-md text-on-surface font-bold truncate">{name}</p>
                  <p className="text-[11px] text-on-surface-variant/60">{label}</p>
                </div>
                <span className="text-label-sm text-primary font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                  Continue
                </span>
              </Link>
            );
          })}
        </div>
      )}

      {campaigns.length > 0 && (
        <Link
          href="/campaigns"
          className="mt-4 w-full block text-center py-3 rounded-xl border border-primary/40 text-primary text-sm font-bold hover:bg-primary/5 transition-all"
        >
          View All Campaigns
        </Link>
      )}
    </div>
  );
}

/* ─── Quick Actions ─── */
function QuickActionsSection() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <QuickActionCard
        href="/discovery"
        icon="add_circle"
        label="New Campaign"
        color="text-primary"
        groupHoverBorder="hover:border-primary/50"
      />
      <Link
        href="/discovery"
        className="glass-panel p-6 rounded-3xl flex flex-col items-center justify-center gap-4 group hover:border-secondary/50 transition-all active:scale-95"
      >
        <div className="w-16 h-16 rounded-2xl bg-secondary/10 flex items-center justify-center text-secondary group-hover:scale-110 transition-transform">
          <Icon name="upload_file" className="text-4xl" fill />
        </div>
        <span className="text-headline-md text-on-surface">Import Leads</span>
      </Link>
      <Link
        href="/campaign-intelligence"
        className="glass-panel p-6 rounded-3xl flex flex-col items-center justify-center gap-4 group hover:border-tertiary/50 transition-all active:scale-95"
      >
        <div className="w-16 h-16 rounded-2xl bg-tertiary/10 flex items-center justify-center text-tertiary group-hover:scale-110 transition-transform">
          <Icon name="insights" className="text-4xl" fill />
        </div>
        <span className="text-headline-md text-on-surface">Analytics</span>
      </Link>
    </div>
  );
}

function QuickActionCard({
  href,
  icon,
  label,
  color,
  groupHoverBorder,
}: {
  href: string;
  icon: string;
  label: string;
  color: string;
  groupHoverBorder: string;
}) {
  return (
    <Link
      href={href}
      className={`glass-panel p-6 rounded-3xl flex flex-col items-center justify-center gap-4 group ${groupHoverBorder} transition-all active:scale-95`}
    >
      <div
        className={`w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center ${color} group-hover:scale-110 transition-transform`}
      >
        <Icon name={icon} className="text-4xl" fill />
      </div>
      <span className="text-headline-md text-on-surface">{label}</span>
    </Link>
  );
}
