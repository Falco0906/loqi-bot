"use client";

import { useEffect, useState } from "react";
import { listCampaigns, updateCampaign, archiveCampaign } from "../../../lib/api";
import CampaignCard from "../../../components/campaigns/CampaignCard";
import Icon from "../../../components/shared/Icon";

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

  async function handleGenerate(id: string) {
    if (!sessionToken) return;
    try {
      await updateCampaign(sessionToken, id, { status: "ready" });
      fetchCampaigns();
    } catch { /* silent */ }
  }

  async function handleArchive(id: string) {
    if (!sessionToken) return;
    try {
      await archiveCampaign(sessionToken, id);
      fetchCampaigns();
    } catch { /* silent */ }
  }

  const activeCampaigns = campaigns.filter((c) => c.status !== "archived");
  const archivedCampaigns = campaigns.filter((c) => c.status === "archived");

  const SORT_ORDER: Record<string, number> = {
    planning: 0,
    ready: 1,
    generating: 2,
    draft_review: 3,
    ready_to_send: 4,
    completed: 5,
  };

  function sortFn(a: Record<string, unknown>, b: Record<string, unknown>) {
    return (SORT_ORDER[a.status as string] ?? 99) - (SORT_ORDER[b.status as string] ?? 99);
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Icon name="campaign" className="text-primary text-xl" />
          </div>
          <div>
            <h1 className="text-headline-md text-on-surface font-bold">Campaigns</h1>
            <p className="text-body-md text-on-surface-variant/60">
              {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} total
              {activeCampaigns.length > 0 ? ` \u00b7 ${activeCampaigns.length} active` : ""}
            </p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex items-center gap-3 text-on-surface-variant">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              Loading campaigns...
            </div>
          </div>
        ) : campaigns.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
              <Icon name="campaign" className="text-4xl" />
            </div>
            <p className="text-body-lg text-on-surface-variant/60">No campaigns yet</p>
            <p className="mt-1 text-body-md text-on-surface-variant/40 max-w-sm">
              Find leads in Discovery and create a campaign from the batch actions bar.
            </p>
          </div>
        ) : (
          <>
            {activeCampaigns.length > 0 && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
                {activeCampaigns.sort(sortFn).map((c) => (
                  <CampaignCard
                    key={c.id as string}
                    id={c.id as string}
                    name={c.name as string}
                    status={c.status as string}
                    leadCount={c.lead_count as number}
                    pendingDrafts={c.pending_drafts as number}
                    approvedDrafts={c.approved_drafts as number}
                    createdAt={c.created_at as string}
                    updatedAt={c.updated_at as string}
                    onGenerate={() => handleGenerate(c.id as string)}
                    onArchive={() => handleArchive(c.id as string)}
                  />
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
                      leadCount={c.lead_count as number}
                      pendingDrafts={c.pending_drafts as number}
                      approvedDrafts={c.approved_drafts as number}
                      createdAt={c.created_at as string}
                      updatedAt={c.updated_at as string}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
