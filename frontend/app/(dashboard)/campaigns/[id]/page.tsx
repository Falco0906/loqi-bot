"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { getCampaign, updateCampaign, generateCampaignDrafts, getCampaignGenerationStatus } from "../../../../lib/api";
import DraftReviewWorkspace from "../../../../components/draft/DraftReviewWorkspace";
import CampaignStatusBadge from "../../../../components/campaigns/CampaignStatusBadge";
import CampaignDraftList from "../../../../components/campaigns/CampaignDraftList";
import Icon from "../../../../components/shared/Icon";
import { toast } from "../../../../components/shared/Toast";
import { usePageContext } from "../../../../hooks/usePageContext";
import { useActionHandlers } from "../../../../hooks/useActionHandlers";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

const TABS = ["Overview", "Strategy", "Leads", "Drafts", "Replies", "Analytics", "Settings"] as const;
type Tab = typeof TABS[number];

export default function CampaignDetailPage() {
  const params = useParams();
  const router = useRouter();
  const campaignId = params.id as string;
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [campaign, setCampaign] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("Overview");
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState<{ total: number; completed: number } | null>(null);
  const [campaignError, setCampaignError] = useState<string | null>(null);
  const [nameEdit, setNameEdit] = useState("");

  usePageContext("Campaign", {
    campaign_id: campaignId,
    campaign_name: campaign?.name ?? null,
    status: campaign?.status ?? null,
    lead_count: campaign?.lead_count ?? 0,
    pending_drafts: campaign?.pending_drafts ?? 0,
    approved_drafts: campaign?.approved_drafts ?? 0,
    total_drafts: (campaign?.pending_drafts as number ?? 0) + (campaign?.approved_drafts as number ?? 0),
    tab,
    generating,
    messaging_strategy: campaign?.messaging_strategy ?? null,
  });

  useActionHandlers({
    generate_drafts: handleGenerateDrafts,
  });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  useEffect(() => { setNameEdit(campaign?.name as string || ""); }, [campaign?.name]);

  async function refreshCampaign() {
    if (!sessionToken) return;
    try {
      const res = await getCampaign(sessionToken, campaignId);
      if (res.ok) setCampaign(res.campaign);
    } catch { /* silent */ }
  }

  useEffect(() => {
    if (!sessionToken) return;
    (async () => {
      setLoading(true);
      try {
        await refreshCampaign();
      } catch { /* silent */ } finally {
        setLoading(false);
      }
    })();
  }, [sessionToken, campaignId]);

  async function handleGenerateDrafts() {
    if (!sessionToken) return;
    setGenerating(true);
    setGenProgress(null);
    setCampaignError(null);
    try {
      const res = await generateCampaignDrafts(sessionToken, campaignId);
      if (res.ok) {
        await updateCampaign(sessionToken, campaignId, { status: "generating" });
        await refreshCampaign();
        const poll = setInterval(async () => {
          try {
            const status = await getCampaignGenerationStatus(sessionToken, campaignId);
            if (status.ok) {
              if (status.active === false) {
                clearInterval(poll);
                setGenerating(false);
                setGenProgress(null);
                await updateCampaign(sessionToken, campaignId, { status: "draft_review" });
                await refreshCampaign();
              } else {
                setGenProgress({ total: status.total || 0, completed: status.completed || 0 });
              }
            }
          } catch { /* silent */ }
        }, 800);
      }
    } catch (err) {
      setGenerating(false);
      setCampaignError(err instanceof Error ? err.message : "Generation failed");
    }
  }

  if (loading) {
    return (
      <div className="h-full flex flex-col overflow-hidden animate-fade-in">
        <div className="shrink-0 border-b border-outline-variant/10 px-6 py-5">
          <div className="max-w-6xl mx-auto flex items-center gap-4">
            <div className="h-8 w-8 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
            <div className="space-y-2">
              <div className="h-6 w-64 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-40 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
            </div>
          </div>
        </div>
        <div className="shrink-0 border-b border-outline-variant/10 px-6">
          <div className="max-w-6xl mx-auto flex gap-1 py-3">
            {[1, 2, 3, 4, 5, 6, 7].map((i) => (
              <div key={i} className="h-8 w-20 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="lg:col-span-2 space-y-5">
              <div className="h-48 rounded-2xl bg-surface-lowest border border-outline-variant/10 animate-skeleton-pulse" />
              <div className="h-32 rounded-2xl bg-surface-lowest border border-outline-variant/10 animate-skeleton-pulse" />
            </div>
            <div className="space-y-5">
              <div className="h-64 rounded-2xl bg-surface-lowest border border-outline-variant/10 animate-skeleton-pulse" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
          <Icon name="search_off" className="text-3xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/80 font-medium">Campaign not found</p>
        <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm">
          This campaign may have been deleted or the link may be incorrect.
        </p>
        <button
          onClick={() => router.push("/campaigns")}
          className="mt-6 inline-flex items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary hover:brightness-110 active:scale-[0.97] transition-all"
        >
          Back to Campaigns
        </button>
      </div>
    );
  }

  const name = campaign.name as string;

  const status = campaign.status as string;
  const leadCount = campaign.lead_count as number;
  const pendingDrafts = campaign.pending_drafts as number;
  const approvedDrafts = campaign.approved_drafts as number;
  const strategy = campaign.strategy as Record<string, unknown> | undefined;
  const searchQuery = campaign.search_query as string;
  const createdAt = campaign.created_at as string;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-outline-variant/10 px-6 py-4">
        <div className="flex items-center justify-between max-w-6xl mx-auto">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push("/campaigns")}
              className="p-1.5 rounded-lg hover:bg-surface-high text-on-surface-variant/60 hover:text-on-surface transition-all"
            >
              <Icon name="chevron_right" className="rotate-180 text-lg" />
            </button>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-headline-md text-on-surface font-bold">{name}</h1>
                <CampaignStatusBadge status={status} />
              </div>
              <p className="text-label-sm text-on-surface-variant/60 mt-0.5">
                {leadCount} {leadCount === 1 ? "lead" : "leads"} &middot;
                Created {createdAt ? new Date(createdAt).toLocaleDateString() : ""}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="shrink-0 border-b border-outline-variant/10 px-6">
        <div className="max-w-6xl mx-auto flex gap-1 -mb-px">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-4 py-3 text-sm font-medium transition-all duration-150 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 ${
                tab === t
                  ? "text-primary"
                  : "text-on-surface-variant/60 hover:text-on-surface"
              }`}
            >
              {t}
              {tab === t && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-full" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-6xl mx-auto">
          {tab === "Overview" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
              <div className="lg:col-span-2 space-y-5">
                <div className="card-base p-6">
                  <h2 className="text-body-lg text-on-surface font-bold mb-4">Campaign Summary</h2>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-surface/50 rounded-xl p-4 transition-all duration-150 hover:bg-surface-high/30">
                      <p className="text-label-sm text-on-surface-variant/60 mb-1">Status</p>
                      <CampaignStatusBadge status={status} />
                    </div>
                    <div className="bg-surface/50 rounded-xl p-4 transition-all duration-150 hover:bg-surface-high/30">
                      <p className="text-label-sm text-on-surface-variant/60 mb-1">Leads</p>
                      <p className="text-headline-sm text-on-surface font-bold">{leadCount}</p>
                    </div>
                    <div className="bg-surface/50 rounded-xl p-4 transition-all duration-150 hover:bg-surface-high/30">
                      <p className="text-label-sm text-on-surface-variant/60 mb-1">Drafts</p>
                      <p className="text-headline-sm text-on-surface font-bold">
                        {pendingDrafts + approvedDrafts}
                      </p>
                      <p className="text-label-sm text-on-surface-variant/40 mt-1">
                        {pendingDrafts} pending &middot; {approvedDrafts} approved
                      </p>
                    </div>
                  </div>
                </div>

                {generating && genProgress ? (
                  <div className="card-base border-primary/20 bg-primary-container/5 p-6">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-3 h-3 rounded-full bg-primary animate-pulse" />
                      <p className="text-body-md text-on-surface font-bold">Generating drafts...</p>
                    </div>
                    <div className="w-full bg-outline-variant/10 rounded-full h-2 overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all duration-500"
                        style={{ width: `${genProgress.total > 0 ? Math.round((genProgress.completed / genProgress.total) * 100) : 0}%` }}
                      />
                    </div>
                    <p className="text-label-sm text-on-surface-variant/60 mt-2">
                      {genProgress.completed} of {genProgress.total} drafts
                    </p>
                  </div>
                ) : null}

                {campaignError ? (
                  <div className="rounded-xl border border-error/20 bg-error/10 px-5 py-4">
                    <div className="flex items-start gap-3">
                      <Icon name="warning" className="text-error text-lg mt-0.5 shrink-0" />
                      <div>
                        <p className="text-body-md text-on-surface font-bold mb-1">Something went wrong</p>
                        <p className="text-label-sm text-on-surface-variant/80">{campaignError}</p>
                        <p className="text-label-sm text-on-surface-variant/40 mt-1">
                          Try generating drafts again. If the problem persists, check that your campaign has leads assigned.
                        </p>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>

              <div className="space-y-5">
                <div className="card-base p-5">
                  <h2 className="text-body-md text-on-surface font-bold mb-3">Quick Actions</h2>
                  <div className="space-y-2">
                    {status === "planning" || status === "ready" ? (
                      <button
                        onClick={handleGenerateDrafts}
                        disabled={generating}
                        className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg bg-primary text-on-primary text-sm font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                      >
                        {generating && (
                          <svg className="-ml-1 mr-2 h-4 w-4 animate-spin text-on-primary/80" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                        )}
                        {generating ? "Generating Drafts..." : "Generate Drafts"}
                      </button>
                    ) : null}
                    {status === "draft_review" && pendingDrafts > 0 ? (
                      <Link
                        href={`/draft?campaign=${campaignId}`}
                        className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg bg-secondary text-on-primary text-sm font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                      >
                        Continue Draft Review ({pendingDrafts})
                      </Link>
                    ) : null}
                    {status === "generating" ? (
                      <button
                        disabled
                        className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg bg-outline-variant/20 text-on-surface-variant/60 text-sm font-medium cursor-not-allowed"
                      >
                        <svg className="mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Generating Drafts...
                      </button>
                    ) : null}
                    {status === "ready_to_send" ? (
                      <button
                        onClick={async () => {
                          if (sessionToken) {
                            await updateCampaign(sessionToken, campaignId, { status: "completed" });
                            toast("success", "Campaign launched successfully");
                            await refreshCampaign();
                          }
                        }}
                        className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg bg-primary text-on-primary text-sm font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                      >
                        <Icon name="rocket_launch" className="text-sm mr-2" />
                        Launch Campaign
                      </button>
                    ) : null}
                    <button
                      onClick={() => router.push("/discovery")}
                      className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface text-sm font-medium transition-all duration-150 hover:border-primary/40 hover:text-primary active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                    >
                      Add More Leads
                    </button>
                    {status !== "archived" ? (
                      <button
                        onClick={async () => {
                          if (sessionToken) {
                            await updateCampaign(sessionToken, campaignId, { status: "archived" });
                            toast("info", "Campaign paused");
                            router.push("/campaigns");
                          }
                        }}
                        className="w-full inline-flex items-center justify-center px-4 py-2.5 rounded-lg border border-error/20 text-error text-sm font-medium transition-all duration-150 hover:bg-error/5 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                      >
                        Pause Campaign
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "Strategy" && (
            <div className="max-w-3xl">
              {strategy && strategy.campaigns ? (
                <div className="space-y-5">
                  <div className="card-base border-primary/15 bg-primary-container/5 px-6 py-5">
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                        <Icon name="lightbulb" className="text-primary text-base" />
                      </div>
                      <div>
                        <p className="text-label-sm text-primary/70 uppercase tracking-wider font-medium mb-1">
                          Strategy Overview
                        </p>
                        <p className="text-body-md text-on-surface leading-relaxed whitespace-pre-line">
                          {(strategy.overall_recommendation as string) || ""}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4">
                    {(strategy.campaigns as Array<Record<string, unknown>>).map((sc: Record<string, unknown>, i: number) => (
                      <div
                        key={sc.id as string}
                        className="card-base overflow-hidden"
                      >
                        <div className="px-5 py-4 border-b border-outline-variant/10">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                              <Icon name="campaign" className="text-primary text-sm" />
                            </div>
                            <div>
                              <p className="text-body-md text-on-surface font-bold">
                                Campaign {String.fromCharCode(65 + i)}
                              </p>
                              <p className="text-label-sm text-on-surface-variant/60">{sc.name as string}</p>
                            </div>
                          </div>
                        </div>
                        <div className="px-5 py-4 space-y-3">
                          <div className="bg-surface/50 rounded-xl px-4 py-3">
                            <p className="text-label-sm text-on-surface-variant/60 mb-1">Reason</p>
                            <p className="text-body-sm text-on-surface">{sc.reason as string}</p>
                          </div>
                          <div className="bg-primary-container/5 rounded-xl px-4 py-3 border border-primary/10">
                            <p className="text-label-sm text-primary/70 mb-1">Messaging</p>
                            <p className="text-body-sm text-on-surface">{sc.messaging_angle as string}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <div className="w-12 h-12 rounded-xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-3">
                    <Icon name="insights" className="text-2xl" />
                  </div>
                  <p className="text-body-md text-on-surface-variant/60">No strategy data</p>
                  <p className="text-label-sm text-on-surface-variant/40 mt-1">
                    Run campaign analysis from Discovery to generate a strategy.
                  </p>
                </div>
              )}
            </div>
          )}

          {tab === "Leads" && (
            <div className="max-w-4xl">
              {leadCount > 0 ? (
                <div className="space-y-3">
                  {(campaign.leads as Array<Record<string, unknown>> | undefined)?.map((ld, i) => {
                    const name = (ld.name as string) || `${ld.first_name || ""} ${ld.last_name || ""}`.trim() || "Unknown";
                    const company = ld.company as string;
                    const title = ld.title as string;
                    return (
                      <div
                        key={ld.lead_id as string || ld.id as string || i}
                        className="card-base p-4 flex items-center justify-between hover:border-outline-variant/20 transition-all"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-body-md text-on-surface font-bold truncate">{name}</p>
                          <p className="text-label-sm text-on-surface-variant/60 truncate">
                            {[title, company].filter(Boolean).join(" \u2022 ") || "\u2014"}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0 ml-3">
                          {(ld.buying_signals as string[] | undefined)?.slice(0, 2).map((s) => (
                            <span
                              key={s}
                              className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-medium"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <div className="w-12 h-12 rounded-xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-3">
                    <Icon name="groups" className="text-2xl" />
                  </div>
                  <p className="text-body-md text-on-surface-variant/60">No leads in this campaign</p>
                  <p className="text-label-sm text-on-surface-variant/40 mt-1">Leads will appear once you generate a campaign from Discovery.</p>
                </div>
              )}
            </div>
          )}

          {tab === "Drafts" && sessionToken && (
            <CampaignDraftList sessionToken={sessionToken} campaignId={campaignId} />
          )}

          {(tab === "Replies" || tab === "Analytics") && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-12 h-12 rounded-xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-3">
                <Icon name="insights" className="text-2xl" />
              </div>
              <p className="text-body-md text-on-surface-variant/60">Coming soon</p>
              <p className="text-label-sm text-on-surface-variant/40 mt-1">This feature is in development.</p>
            </div>
          )}

          {tab === "Settings" && (
            <div className="max-w-xl space-y-5">
              <div className="card-base p-6">
                <h2 className="text-body-lg text-on-surface font-bold mb-4">Campaign Settings</h2>
                <div className="space-y-4">
                  <div>
                    <label className="text-label-sm text-on-surface-variant/60 block mb-1">Campaign Name</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={nameEdit}
                        onChange={(e) => setNameEdit(e.target.value)}
                        className="flex-1 rounded-xl border border-outline-variant/20 bg-surface-low px-4 py-2.5 text-body-md text-on-surface outline-none focus:border-primary/50"
                      />
                      <button
                        onClick={async () => {
                          if (!sessionToken || !nameEdit.trim()) return;
                          try {
                            await updateCampaign(sessionToken, campaignId, { name: nameEdit.trim() });
                            setCampaign((prev) => prev ? { ...prev, name: nameEdit.trim() } : prev);
                            toast("success", "Name updated");
                          } catch { toast("error", "Failed to rename"); }
                        }}
                        disabled={!nameEdit.trim() || nameEdit.trim() === name}
                        className="px-4 py-2 rounded-xl bg-primary text-on-primary text-sm font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.97] disabled:opacity-40"
                      >
                        Save
                      </button>
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      if (sessionToken) {
                        await updateCampaign(sessionToken, campaignId, { status: "archived" });
                        router.push("/campaigns");
                      }
                    }}
                    className="px-5 py-2.5 rounded-lg border border-error/20 text-error text-sm font-medium hover:bg-error/5 transition-all"
                  >
                    Archive Campaign
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
