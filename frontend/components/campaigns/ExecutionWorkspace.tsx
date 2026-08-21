"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { getCampaign, getCampaignTimeline } from "../../lib/api";
import type { CampaignLaunchProgress } from "../../lib/domain";

type Props = {
  token: string | null;
  campaignId: string;
  campaignName: string;
  initial?: CampaignLaunchProgress;
  launched: boolean;
  onProgress?: (p: CampaignLaunchProgress) => void;
  onTerminal?: (p: CampaignLaunchProgress) => void;
  onCollapse?: () => void;
};

type TimelineEvent = {
  type: string;
  timestamp: string;
  actor: string;
  data: Record<string, unknown>;
};

const TERMINAL = new Set(["launched", "failed", "partial"]);

const EVENT_META: Record<string, { icon: string; tone: "success" | "error" | "primary" | "muted" }> = {
  draft_sent: { icon: "check_circle", tone: "success" },
  draft_approved: { icon: "check", tone: "primary" },
  draft_rejected: { icon: "block", tone: "muted" },
  draft_generated: { icon: "edit_note", tone: "primary" },
  draft_updated: { icon: "edit_note", tone: "muted" },
  draft_failed: { icon: "error", tone: "error" },
  campaign_status_changed: { icon: "rocket_launch", tone: "primary" },
  campaign_created: { icon: "add_circle", tone: "muted" },
  campaign_updated: { icon: "edit", tone: "muted" },
};

function eventLabel(e: TimelineEvent): string {
  const d = e.data || {};
  switch (e.type) {
    case "draft_sent":
      return `Delivered to ${String(d.recipient_email || "recipient")}`;
    case "draft_failed":
      return `Send failed — ${String(d.error || "unknown error")}`;
    case "draft_approved":
      return "Draft approved";
    case "draft_updated":
      return `Draft updated${d.change_summary ? ` — ${String(d.change_summary)}` : ""}`;
    case "draft_generated":
      return "Draft generated";
    case "campaign_status_changed":
      return `Campaign moved to ${String(d.status || "").replace(/_/g, " ")}`;
    case "campaign_created":
      return "Campaign created";
    case "campaign_updated":
      return "Campaign updated";
    default:
      return e.type.replace(/_/g, " ");
  }
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return (
    date.toLocaleDateString([], { month: "short", day: "numeric" }) +
    " · " +
    date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
  );
}

/**
 * Live Execution Workspace. Appears the moment a launch begins and stays until
 * the user closes it. Progress comes from durable counters (queued/sending/
 * delivered/failed), the timeline from the World Model event log — both
 * polled (no WebSockets). On completion it turns into the terminal view with
 * Open Inbox + Return to Campaign. Every campaigned section below stays fully
 * visible; nothing is hidden, nothing reloads.
 */
export default memo(function ExecutionWorkspace({
  token,
  campaignId,
  campaignName,
  initial,
  launched,
  onProgress,
  onTerminal,
  onCollapse,
}: Props) {
  const [progress, setProgress] = useState<CampaignLaunchProgress>(
    initial ?? { status: "sending", total: 0, sent: 0, failed: 0 },
  );
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [completedAt, setCompletedAt] = useState("");
  const terminalNotified = useRef(false);
  const pollInFlight = useRef(false);

  const status = progress.status || "sending";
  const inFlight = status === "sending";
  const done = TERMINAL.has(status);

  useEffect(() => {
    if (launched && !done && terminalNotified.current) terminalNotified.current = false;
  }, [done, launched]);

  const poll = useCallback(async () => {
    if (!token || pollInFlight.current) return;
    // PR-P1.4: shared guard — the immediate effect and the interval effect
    // can both call poll(); never let two run at once.
    pollInFlight.current = true;
    try {
      const [c, t] = await Promise.all([
        getCampaign(token, campaignId),
        getCampaignTimeline(token, campaignId),
      ]);
      if (c.ok && c.campaign) {
        const nested = (c.campaign.launch as Record<string, unknown> | undefined) || {};
        const total = Number(nested.total ?? c.campaign.launch_total ?? 0);
        const sent = Number(nested.sent ?? c.campaign.launch_sent ?? 0);
        const failed = Number(nested.failed ?? c.campaign.launch_failed ?? 0);
        const nestedStatus = String(nested.status || "");
        const next: CampaignLaunchProgress = {
          status:
            nestedStatus || (total > 0 && sent >= total ? "launched" : "sending"),
          total,
          sent,
          failed,
        };
        setProgress(next);
        onProgress?.(next);
        if (next.status === "sending" && total > 0 && sent >= total) {
          setProgress((cur) => ({ ...cur, status: "launched" }));
        }
      }
      if (t.ok) {
        setEvents(
          t.events.map((e) => ({
            type: e.type,
            timestamp: e.timestamp,
            actor: e.actor || "system",
            data: (e.data as Record<string, unknown> | undefined) || {},
          })),
        );
      }
    } catch {
      /* keep silent — polling continues */
    } finally {
      pollInFlight.current = false;
    }
  }, [token, campaignId, onProgress]);

  useEffect(() => {
    if (!launched && !done && !inFlight) return;
    void poll();
  }, [launched, done, inFlight, poll]);

  useEffect(() => {
    if (!inFlight) return;
    const id = window.setInterval(() => void poll(), 2000);
    return () => window.clearInterval(id);
  }, [inFlight, poll]);

  useEffect(() => {
    if (done && !terminalNotified.current && !collapsed) {
      terminalNotified.current = true;
      setCompletedAt(events[events.length - 1]?.timestamp || new Date().toISOString());
      onTerminal?.(progress);
    }
  }, [done, events, progress, collapsed, onTerminal]);

  const terminal = done && !collapsed;

  return (
    <div id="execution-workspace">
      <div className="rounded-xl border border-outline-variant/10 bg-surface-lowest overflow-hidden animate-conversation-fade ambient-shadow">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-outline-variant/10">
          <div className="flex items-center gap-3">
            <span
              className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                inFlight ? "bg-primary/10" : done ? "bg-success/10" : "bg-outline-variant/10"
              }`}
            >
              <span
                className={`material-symbols-outlined text-lg ${
                  inFlight
                    ? "text-primary animate-pulse"
                    : done && progress.failed === 0
                      ? "text-success"
                      : done
                        ? "text-secondary"
                        : "text-on-surface-variant"
                }`}
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                {inFlight ? "progress_activity" : done ? "task_alt" : "rocket_launch"}
              </span>
            </span>
            <div>
              <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
                Execution Workspace
              </p>
              <h3 className="text-lg font-serif text-on-surface font-normal truncate max-w-[60vw]">
                {campaignName}
              </h3>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {inFlight && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 text-primary px-3 py-1 text-[11px] font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                Sending…
              </span>
            )}
            {terminal && progress.failed === 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 text-success px-3 py-1 text-[11px] font-semibold">
                Delivered
              </span>
            )}
            {(terminal && progress.failed > 0 && progress.sent > 0) || status === "partial" ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary/10 text-secondary px-3 py-1 text-[11px] font-semibold">
                Partial — {progress.failed} failed
              </span>
            ) : null}
            {terminal && progress.sent === 0 && progress.failed > 0 ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-error/10 text-error px-3 py-1 text-[11px] font-semibold">
                Failed
              </span>
            ) : null}
            {terminal && completedAt ? (
              <span className="text-[11px] text-on-surface-variant/50">
                Completed {formatClock(completedAt)}
              </span>
            ) : null}
          </div>
        </div>

        {/* ─── Stats + progress ─── */}
        <div className="px-5 py-5">
          <div className="grid grid-cols-4 gap-3">
            <StatCard label="Queued" value={Math.max(0, progress.total - progress.sent - progress.failed)} tone="muted" />
            <StatCard label="Sending" value={inFlight ? 1 : 0} tone="primary" />
            <StatCard label="Delivered" value={progress.sent} tone="success" />
            <StatCard label="Failed" value={progress.failed} tone={progress.failed > 0 ? "danger" : "muted"} />
          </div>

          <div className="mt-5">
            <div className="flex items-center justify-between text-xs text-on-surface-variant/70 mb-1.5">
              <span>
                {progress.sent} of {progress.total} delivered
              </span>
              <span>{progress.total > 0 ? Math.round((progress.sent / progress.total) * 100) : 0}%</span>
            </div>
            <div className="h-2 rounded-full bg-outline-variant/15 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  inFlight
                    ? "bg-primary"
                    : progress.failed > 0
                      ? "bg-secondary"
                      : "bg-success"
                }`}
                style={{ width: `${progress.total > 0 ? (progress.sent / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>

          {/* ─── Live timeline ─── */}
          {!collapsed && (
            <div className="mt-6">
              <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-3">
                Live timeline
              </p>
              <div className="space-y-0">
                {events.length === 0 ? (
                  <p className="text-sm text-on-surface-variant/50 py-2">
                    {inFlight ? "Launching…" : "No activity recorded yet."}
                  </p>
                ) : (
                  events
                    .slice()
                    .reverse()
                    .slice(0, 12)
                    .map((e, i) => {
                    const meta = EVENT_META[e.type] || { icon: "campaign", tone: "muted" as const };
                    const toneClass =
                      meta.tone === "success"
                        ? "text-success"
                        : meta.tone === "error"
                          ? "text-error"
                          : meta.tone === "primary"
                            ? "text-primary"
                            : "text-on-surface-variant/60";
                    return (
                      <div key={`${e.timestamp}-${i}`} className="flex items-center gap-3 py-2">
                        <span className={`material-symbols-outlined text-base ${meta.tone === "error" ? "text-error" : "text-on-surface-variant/40"}`} style={{ fontVariationSettings: "'FILL' 1" }}>
                          {meta.icon}
                        </span>
                        <span className="min-w-0 flex-1 text-sm text-on-surface truncate">
                          {eventLabel(e)}
                        </span>
                        <span className="shrink-0 text-[11px] text-on-surface-variant/40">
                          {formatTime(e.timestamp)}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Terminal view — success → Open Inbox; failure stays in workspace ── */}
        {!collapsed && terminal && (
          <div className="px-5 py-5 border-t border-outline-variant/10 bg-surface-container-low/50">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                {progress.failed === 0 ? (
                  <>
                    <p className="text-sm font-semibold text-success">Launch delivered</p>
                    <p className="text-xs text-on-surface-variant/70 mt-0.5">
                      {progress.sent} outreach emails are live. Replies and follow-ups settle in Inbox.
                    </p>
                  </>
                ) : progress.sent > 0 ? (
                  <>
                    <p className="text-sm font-semibold text-secondary">Partial launch</p>
                    <p className="text-xs text-on-surface-variant/70 mt-0.5">
                      {progress.sent} delivered, {progress.failed} failed. Review failures in Inbox.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-semibold text-error">Launch failed</p>
                    <p className="text-xs text-on-surface-variant/70 mt-0.5">
                      {progress.failed} sends failed. Check your Gmail connection and try again.
                    </p>
                  </>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    setCollapsed(true);
                    onCollapse?.();
                  }}
                  className="rounded-lg border border-outline-variant/30 px-4 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
                >
                  Return to campaign
                </button>
                <a
                  href="/inbox"
                  className="inline-flex items-center gap-2 rounded-lg bg-primary text-on-primary px-4 py-2 text-xs font-semibold hover:brightness-110 transition-all"
                >
                  Open Inbox
                  <span className="material-symbols-outlined text-sm">arrow_forward</span>
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "danger" | "primary" | "muted";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "danger"
        ? "text-error"
        : tone === "primary"
          ? "text-primary"
          : "text-on-surface";
  return (
    <div className="rounded-lg border border-outline-variant/10 bg-surface border-outline-variant/5 px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium">{label}</p>
      <p className={`text-lg font-semibold tabular-nums mt-0.5 ${toneClass}`}>{value}</p>
    </div>
  );
}
