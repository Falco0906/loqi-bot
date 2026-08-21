"use client";

import { useEffect, useState } from "react";
import { listCampaigns, updateCampaign, archiveCampaign, duplicateCampaign, deleteCampaign } from "../../../lib/api";
import CampaignCard from "../../../components/campaigns/CampaignCard";
import Icon from "../../../components/shared/Icon";
import { toast } from "../../../components/shared/Toast";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import { useTellLoqi } from "../../../hooks/useTellLoqi";
import { useActionHandlers } from "../../../hooks/useActionHandlers";
import { buildResearchUrl, campaignAttachContext } from "../../../lib/discovery-mode";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

export default function CampaignsPage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  async function fetchCampaigns() {
    if (!sessionToken) return;
    setLoading(true);
    try {
      const res = await listCampaigns(sessionToken);
      if (res.ok && Array.isArray(res.campaigns)) {
        setCampaigns(res.campaigns);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCampaigns();
  }, [sessionToken]);

  async function handleArchive(id: string) {
    if (!sessionToken) return;
    try {
      await archiveCampaign(sessionToken, id);
      toast("success", "Campaign archived");
      fetchCampaigns();
    } catch { toast("error", "Failed to archive campaign"); }
  }

  async function handleRename(id: string, currentName: string) {
    const newName = window.prompt("Rename campaign", currentName);
    if (!newName || newName.trim() === currentName || !sessionToken) return;
    try {
      await updateCampaign(sessionToken, id, { name: newName.trim() });
      toast("success", "Campaign renamed");
      fetchCampaigns();
    } catch { toast("error", "Failed to rename campaign"); }
  }

  async function handleUnarchive(id: string) {
    if (!sessionToken) return;
    try {
      await updateCampaign(sessionToken, id, { status: "planning" });
      toast("success", "Campaign restored");
      fetchCampaigns();
    } catch { toast("error", "Failed to restore campaign"); }
  }

  async function handleDuplicate(id: string) {
    if (!sessionToken) return;
    try {
      const res = await duplicateCampaign(sessionToken, id);
      if (!res.ok) throw new Error("duplicate failed");
      const copy = res.campaign as Record<string, unknown>;
      toast("success", `Duplicated — ${String(copy.name || "copy")} created`);
      fetchCampaigns();
    } catch { toast("error", "Failed to duplicate campaign"); }
  }

  async function handleDelete(id: string) {
    if (!sessionToken) return;
    if (!window.confirm("Delete this campaign? This removes it from your workspace. Its strategy and leads are removed with it.")) return;
    try {
      await deleteCampaign(sessionToken, id);
      toast("success", "Campaign deleted");
      fetchCampaigns();
    } catch { toast("error", "Failed to delete campaign"); }
  }

  useActionHandlers({
    generate_strategy: (params) => {
      const campaignId = (params?.campaignId as string) || String(campaigns[0]?.id || "");
      if (campaignId) window.location.href = `/campaigns/${campaignId}`;
    },
    add_leads: (params) => {
      const campaignId = (params?.campaignId as string) || String(campaigns[0]?.id || "");
      if (campaignId) {
        const target = campaigns.find((c) => String(c.id) === campaignId) || null;
        const ctx = campaignAttachContext(target || { id: campaignId });
        if (ctx) window.location.href = buildResearchUrl(ctx);
      }
    },
    duplicate_campaign: async (params) => {
      const campaignId = (params?.campaignId as string) || String(campaigns[0]?.id || "");
      if (campaignId && sessionToken) await handleDuplicate(campaignId);
    },
    delete_campaign: async (params) => {
      const campaignId = (params?.campaignId as string) || String(campaigns[0]?.id || "");
      if (campaignId && sessionToken) await handleDelete(campaignId);
    },
    open_campaign: (params) => {
      const campaignId = params?.campaignId as string | undefined;
      if (campaignId) window.location.href = `/campaigns/${campaignId}`;
    },
  });

  const visibleCampaigns = campaigns.filter((c) => c.status !== "deleted");
  const activeCampaigns = visibleCampaigns.filter((c) => c.status !== "archived");
  const archivedCampaigns = visibleCampaigns.filter((c) => c.status === "archived");

  const SORT_ORDER: Record<string, number> = {
    strategy: 0,
    leads: 1,
    drafts: 2,
    review: 3,
    sending: 4,
  };

  const tellLoqi = useTellLoqi("Campaigns", {
    active: activeCampaigns.length,
    total: visibleCampaigns.length,
  });

  function sortFn(a: Record<string, unknown>, b: Record<string, unknown>) {
    const stepA = SORT_ORDER[a.current_step as string] ?? 99;
    const stepB = SORT_ORDER[b.current_step as string] ?? 99;
    return stepA - stepB;
  }

  return (
    <WorkspaceContainer>
      <div className="h-full overflow-y-auto px-6 py-6">
        <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between gap-3 mb-8">
          <span className="text-xs font-bold uppercase tracking-widest text-primary bg-primary/10 rounded-full px-3 py-1.5">
            {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} total
            {activeCampaigns.length > 0 ? ` \u00b7 ${activeCampaigns.length} active` : ""}
          </span>
          <a href="/campaigns/new" className="rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary hover:brightness-110">Create Campaign</a>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fade-in">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="card-base p-5 space-y-4 animate-skeleton-pulse"
                style={{ animationDelay: `${i * 0.05}s` }}>
                <div className="h-5 w-2/3 bg-surface-high/50 rounded-lg" />
                <div className="h-3 w-1/3 bg-surface-high/50 rounded-lg" />
                <div className="flex gap-2">
                  <div className="h-6 w-16 bg-surface-high/50 rounded-full" />
                  <div className="h-6 w-16 bg-surface-high/50 rounded-full" />
                </div>
              </div>
            ))}
          </div>
        ) : campaigns.length === 0 ? (
          <>
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <Icon name="campaign" className="text-3xl" />
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No campaigns yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                Find leads in Discovery and create a campaign from the batch actions bar.
              </p>
              <a
                href="/discovery"
                className="mt-6 inline-flex items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary hover:brightness-110 active:scale-[0.97] transition-all"
              >
                Discover Leads
              </a>
            </div>
            {/* Tell Loqi */}
            <div className="mt-16 pt-8 border-t border-outline-variant/20">
              <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
                <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                  Tell Loqi...
                </label>
                <div className="flex items-end gap-3 px-2 pb-1">
                  <textarea
                    className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                    placeholder="How are my campaigns performing?"
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
                  onClick={() => void tellLoqi.submit("Help me plan my first outbound campaign.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  PLAN FIRST CAMPAIGN
                </button>
                <button
                  type="button"
                  onClick={() => void tellLoqi.submit("Find leads in enterprise SaaS.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  FIND LEADS
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
            {activeCampaigns.length > 0 && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
                {activeCampaigns.sort(sortFn).map((c, i) => (
                  <div key={c.id as string} className="animate-slide-up" style={{ animationDelay: `${i * 0.04}s` }}>
                    <CampaignCard
                      id={c.id as string}
                      name={c.name as string}
                      status={c.status as string}
                      step={c.current_step as string}
                      leadCount={c.lead_count as number}
                      pendingDrafts={c.pending_drafts as number}
                      approvedDrafts={c.approved_drafts as number}
                      createdAt={c.created_at as string}
                      updatedAt={c.updated_at as string}
                      onArchive={() => handleArchive(c.id as string)}
                      onDuplicate={() => handleDuplicate(c.id as string)}
                      onDelete={() => handleDelete(c.id as string)}
                      onRename={() => handleRename(c.id as string, c.name as string)}
                    />
                  </div>
                ))}
              </div>
            )}

            {archivedCampaigns.length > 0 && (
              <div>
                <h2 className="text-label-sm text-on-surface-variant/40 uppercase tracking-wider font-medium mb-4">
                  Archived ({archivedCampaigns.length})
                </h2>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {archivedCampaigns.map((c) => (
                    <CampaignCard
                      key={c.id as string}
                      id={c.id as string}
                      name={c.name as string}
                      status={c.status as string}
                      step={c.current_step as string}
                      leadCount={c.lead_count as number}
                      pendingDrafts={c.pending_drafts as number}
                      approvedDrafts={c.approved_drafts as number}
                      createdAt={c.created_at as string}
                      updatedAt={c.updated_at as string}
                      onUnarchive={() => handleUnarchive(c.id as string)}
                      onRename={() => handleRename(c.id as string, c.name as string)}
                    />
                  ))}
                </div>
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
                    placeholder="How are my campaigns performing?"
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
                  onClick={() => void tellLoqi.submit("Give me a performance summary of all active campaigns.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  SUMMARIZE PERFORMANCE
                </button>
                <button
                  type="button"
                  onClick={() => void tellLoqi.submit("Compare my campaigns and recommend which needs attention.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  COMPARE CAMPAIGNS
                </button>
                <button
                  type="button"
                  onClick={() => void tellLoqi.submit("Suggest optimizations for my underperforming campaigns.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  SUGGEST OPTIMIZATIONS
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
    </WorkspaceContainer>
  );
}
