"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { approveDraft, listCampaignDrafts } from "../../lib/api";

type CampaignDraft = {
  id: string;
  campaign_id?: string;
  lead?: Record<string, unknown>;
  subject?: string;
  text: string;
  status: string;
  tone?: string;
  length?: string;
  created_at?: string;
};

function leadName(lead: Record<string, unknown> | undefined): string {
  if (!lead) return "Unknown";
  return String(
    lead.name || lead.full_name || lead.first_name || lead.email || "Unknown",
  );
}

/**
 * Inline drafts as the natural continuation of a campaign: strategy stays
 * visible above, leads stay visible above, drafts appear underneath — nothing
 * disappears. Full review/refinement happens in the dedicated Draft Review
 * workspace.
 */
function CampaignDraftsSection({
  token,
  campaignId,
  generating,
  step,
  locked,
}: {
  token: string | null;
  campaignId: string;
  generating: boolean;
  step: string;
  locked?: boolean;
}) {
  const [drafts, setDrafts] = useState<CampaignDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  // PR-P1.4: prevents overlapping polls when a fetch outlives its interval.
  const fetchInFlight = useRef(false);

  const fetchDrafts = useCallback(async (silent = false) => {
    if (!token || fetchInFlight.current) return;
    fetchInFlight.current = true;
    if (!silent) setLoading(true);
    try {
      const res = await listCampaignDrafts(token, campaignId);
      if (res.ok && Array.isArray(res.drafts)) {
        setDrafts(res.drafts as CampaignDraft[]);
      }
    } catch {
      /* silent */
    } finally {
      fetchInFlight.current = false;
      if (!silent) setLoading(false);
    }
  }, [token, campaignId]);

  useEffect(() => {
    void fetchDrafts();
  }, [fetchDrafts]);

  useEffect(() => {
    if (generating) {
      const id = window.setInterval(() => void fetchDrafts(true), 2500);
      return () => window.clearInterval(id);
    }
  }, [generating, fetchDrafts]);

  async function toggleApprove(draft: CampaignDraft) {
    if (!token) return;
    setTogglingId(draft.id);
    try {
      const res = await approveDraft(token, draft.id);
      if (res.ok) {
        const updated = res.draft;
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === draft.id ? { ...d, status: String(updated.status || "") } : d,
          ),
        );
      }
    } catch {
      /* silent */
    } finally {
      setTogglingId(null);
    }
  }

  const pending = drafts.filter((d) => d.status === "pending" || d.status === "needs_review");
  const approved = drafts.filter((d) => d.status === "approved");
  const sent = drafts.filter((d) => d.status === "sent" || d.status === "scheduled");
  const total = drafts.length;

  const showGenerating = generating || (total === 0 && loading);

  if (total === 0 && !generating) {
    return null;
  }

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-outline-variant/20 pb-4">
        <div>
          <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
            Campaign Drafts
          </span>
          <h4 className="text-xl font-serif text-on-surface mt-1 font-normal">
            {total} draft{total === 1 ? "" : "s"}
          </h4>
        </div>
        {!generating && total > 0 && !locked && (
          <a
            href={`/draft?campaign=${encodeURIComponent(campaignId)}`}
            className="rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
          >
            Open Draft Workspace →
          </a>
        )}
      </div>

      {showGenerating ? (
        <div className="mt-4 p-6 rounded-xl border border-outline-variant/10 bg-surface-lowest flex items-center gap-3">
          <span className="w-5 h-5 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
          <div>
            <p className="text-sm text-on-surface-variant/80">Loqi is writing drafts for your leads…</p>
            <p className="text-xs text-on-surface-variant/50">
              Personalized outreach is generated one lead at a time.
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-4 divide-y divide-outline-variant/10 border border-outline-variant/10 rounded-xl bg-surface-lowest overflow-hidden">
          {sent.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium">
                Sent ({sent.length})
              </p>
              {sent.map((d) => (
                <DraftRow key={d.id} draft={d} />
              ))}
            </div>
          )}
          {approved.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium">
                Approved ({approved.length})
              </p>
              {approved.map((d) => (
                <DraftRow
                  key={d.id}
                  draft={d}
                  onToggle={locked ? undefined : () => void toggleApprove(d)}
                  toggling={togglingId === d.id}
                />
              ))}
            </div>
          )}
          {pending.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium">
                Pending ({pending.length})
              </p>
              {pending.map((d) => (
                <DraftRow
                  key={d.id}
                  draft={d}
                  onToggle={locked ? undefined : () => void toggleApprove(d)}
                  toggling={togglingId === d.id}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {step === "sending" && (
        <p className="mt-3 text-xs text-on-surface-variant/60">
          All drafts approved — this campaign is ready to launch.
        </p>
      )}
    </section>
  );
}

function DraftRow({
  draft,
  onToggle,
  toggling,
}: {
  draft: CampaignDraft;
  onToggle?: () => void;
  toggling?: boolean;
}) {
  const approved = draft.status === "approved";
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="min-w-0">
        {draft.subject ? (
          <p className="text-sm font-medium text-on-surface truncate">{draft.subject}</p>
        ) : null}
        <p className={`text-sm text-on-surface truncate ${draft.subject ? "text-on-surface-variant/80" : "font-medium"}`}>
          {draft.text}
        </p>
        <p className="mt-0.5 text-xs text-on-surface-variant/50 truncate">
          {leadName(draft.lead)}
          {draft.tone ? ` · ${draft.tone}` : ""}
        </p>
      </div>
      {onToggle ? (
        <button
          onClick={onToggle}
          disabled={toggling}
          className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-40 ${
            approved
              ? "border-outline-variant/20 text-on-surface-variant hover:border-error/40 hover:text-error"
              : "border-secondary/30 text-secondary hover:bg-secondary/10"
          }`}
        >
          {toggling
            ? "…"
            : approved
              ? "Unapprove"
              : "Approve"}
        </button>
      ) : null}
    </div>
  );
}

export default memo(CampaignDraftsSection);