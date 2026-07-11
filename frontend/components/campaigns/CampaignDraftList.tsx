"use client";

import { useEffect, useState } from "react";
import { listCampaignDrafts, updateDraft, approveDraft } from "../../lib/api";
import Icon from "../shared/Icon";

type DraftEntry = {
  id: string;
  lead: Record<string, unknown>;
  subject?: string;
  text: string;
  status: string;
  created_at?: string;
};

type Props = {
  sessionToken: string;
  campaignId: string;
};

const STATUS_CONFIG: Record<string, { label: string; dot: string }> = {
  pending: { label: "Pending", dot: "bg-warning" },
  approved: { label: "Approved", dot: "bg-success" },
  sent: { label: "Sent", dot: "bg-primary" },
  archived: { label: "Archived", dot: "bg-outline-variant" },
};

function timeAgo(iso: string): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60000) return "just now";
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`;
  return `${Math.floor(ms / 86400000)}d ago`;
}

export default function CampaignDraftList({ sessionToken, campaignId }: Props) {
  const [drafts, setDrafts] = useState<DraftEntry[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetch() {
    setLoading(true);
    try {
      const res = await listCampaignDrafts(sessionToken, campaignId);
      if (res.ok && Array.isArray(res.drafts)) {
        setDrafts(res.drafts as DraftEntry[]);
      }
    } catch { /* silent */ } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetch(); }, [sessionToken, campaignId]);

  async function handleApprove(id: string) {
    try {
      const res = await approveDraft(sessionToken, id);
      if (res.ok) {
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === id ? { ...d, status: (res.draft as Record<string, unknown>).status as string } : d,
          ),
        );
      }
    } catch { /* silent */ }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          Loading drafts...
        </div>
      </div>
    );
  }

  if (drafts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-12 h-12 rounded-xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-3">
          <Icon name="edit_note" className="text-2xl" />
        </div>
        <p className="text-body-md text-on-surface-variant/60">No drafts yet</p>
        <p className="text-label-sm text-on-surface-variant/40 mt-1">Generate drafts from the Strategy tab.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {drafts.map((d) => {
        const cfg = STATUS_CONFIG[d.status] || STATUS_CONFIG.pending;
        const leadName = (d.lead?.name as string) || (d.lead?.company as string) || "Unknown";
        return (
          <div
            key={d.id}
            className="rounded-xl border border-outline-variant/10 bg-surface-lowest p-4 transition-all hover:border-outline-variant/20"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
                  <span className="text-label-sm font-semibold text-on-surface uppercase">
                    {cfg.label}
                  </span>
                  {d.subject ? (
                    <span className="text-body-sm text-on-surface font-medium truncate">
                      {d.subject}
                    </span>
                  ) : null}
                </div>
                <p className="text-label-sm text-on-surface-variant/60">
                  {leadName}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-3">
                <a
                  href={`/draft`}
                  className="px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-xs font-bold hover:bg-primary/20 transition-all"
                >
                  Review
                </a>
                {d.status === "pending" ? (
                  <button
                    onClick={() => handleApprove(d.id)}
                    className="px-3 py-1.5 rounded-lg border border-outline-variant/20 text-on-surface text-xs font-medium hover:border-success/40 hover:text-success transition-all"
                  >
                    Approve
                  </button>
                ) : null}
              </div>
            </div>
            {d.created_at ? (
              <p className="text-label-sm text-on-surface-variant/40">{timeAgo(d.created_at)}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
