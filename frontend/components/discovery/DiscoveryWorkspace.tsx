"use client";

import { useEffect, useRef, useState } from "react";
import { sendMessage, getExportCsvUrl, batchDraft as batchDraftApi, analyzeCampaigns, saveCampaign as saveCampaignApi, generateCampaignDrafts } from "../../lib/api";
import type { Lead } from "../../lib/types";
import Icon from "../shared/Icon";
import LeadCard from "./LeadCard";
import BatchActionBar from "./BatchActionBar";
import BatchProgress from "./BatchProgress";
import ComparePanel from "./ComparePanel";
import SaveCampaignModal from "./SaveCampaignModal";
import PlannerLoading from "../planner/PlannerLoading";
import CampaignPlanner from "../planner/CampaignPlanner";
import StrategyApproval from "../planner/StrategyApproval";
import GenerationProgress from "../planner/GenerationProgress";
import { usePageContext } from "../../hooks/usePageContext";
import { useActionHandlers } from "../../hooks/useActionHandlers";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

type CampaignResult = {
  id: string;
  name: string;
  lead_count: number;
  leads: unknown[];
  primary_signal: string;
  reason: string;
  messaging_angle: string;
  priority: number;
  message_theme: string;
};

export default function DiscoveryWorkspace() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  /* ── Selection ── */
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [lastClicked, setLastClicked] = useState<number | null>(null);

  function toggleSelection(index: number, shiftKey: boolean) {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (shiftKey && lastClicked !== null) {
        const [start, end] = lastClicked < index ? [lastClicked, index] : [index, lastClicked];
        for (let i = start; i <= end; i++) next.add(i);
        return next;
      }
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
    setLastClicked(index);
  }

  function clearSelection() {
    setSelectedIndices(new Set());
    setLastClicked(null);
  }

  /* ── Batch drafting ── */
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchTotal, setBatchTotal] = useState(0);
  const [draftsReady, setDraftsReady] = useState(0);
  const [showDraftNotification, setShowDraftNotification] = useState(false);

  /* ── Campaign Planner ── */
  const [planning, setPlanning] = useState(false);
  const [planResult, setPlanResult] = useState<{
    campaigns: CampaignResult[];
    overallRecommendation: string;
    totalLeads: number;
  } | null>(null);
  const [approval, setApproval] = useState<{
    campaigns: CampaignResult[];
    overallRecommendation: string;
    totalLeads: number;
  } | null>(null);

  /* ── Draft Generation ── */
  const [generating, setGenerating] = useState<{
    campaignId: string;
    campaignName: string;
  } | null>(null);

  /* ── Compare ── */
  const [compareOpen, setCompareOpen] = useState(false);

  /* ── Save Campaign ── */
  const [campaignModal, setCampaignModal] = useState(false);

  /* ── Derived ── */
  const selectedCount = selectedIndices.size;
  const selectedLeads = Array.from(selectedIndices).map((i) => leads[i]).filter(Boolean);

  usePageContext("Discovery", {
    leads_count: leads.length,
    selected_count: selectedCount,
    search_query: searchQuery,
    has_searched: hasSearched,
    selected_names: selectedLeads.map((l) => l.name),
    selected_companies: selectedLeads.map((l) => l.company),
    industries: [...new Set(leads.map((l) => l.company || "").filter(Boolean))],
    signals: [...new Set(leads.flatMap((l) => l.buying_signals || []))],
  });

  useActionHandlers({
    select_all: () => {
      if (leads.length > 0) setSelectedIndices(new Set(leads.map((_, i) => i)));
    },
    clear_selection: clearSelection,
    compare: () => {
      if (selectedIndices.size >= 2) setCompareOpen(true);
    },
    plan_campaign: handlePlanCampaigns,
    search: () => searchInputRef.current?.focus(),
    save_campaign: handleSaveCampaign,
    export_csv: handleExportCSV,
  });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q || !sessionToken || searching) return;

    setSearching(true);
    setError(null);
    setHasSearched(true);
    setLeads([]);
    clearSelection();
    setBatchId(null);
    setDraftsReady(0);
    setShowDraftNotification(false);
    setPlanning(false);
    setPlanResult(null);

    try {
      const res = await sendMessage(sessionToken, q);
      for (const msg of res.messages) {
        const data = msg.data as Record<string, unknown> | undefined;
        const msgLeads = data?.leads;
        if (Array.isArray(msgLeads) && msgLeads.length > 0) {
          setLeads(msgLeads as Lead[]);
          break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  /* ── Campaign Planning ── */
  async function handlePlanCampaigns() {
    if (!sessionToken || selectedIndices.size === 0) return;
    const selectedLeads = Array.from(selectedIndices).map((i) => leads[i]).filter(Boolean);
    setPlanning(true);
    setPlanResult(null);
    setError(null);

    try {
      const res = await analyzeCampaigns(sessionToken, selectedLeads);
      if (res.ok && res.campaigns) {
        setTimeout(() => {
          setPlanning(false);
          setPlanResult({
            campaigns: res.campaigns,
            overallRecommendation: res.overall_recommendation,
            totalLeads: res.total_leads,
          });
        }, 1500);
      }
    } catch (err) {
      setPlanning(false);
      setError(err instanceof Error ? err.message : "Campaign analysis failed");
    }
  }

  function handleAcceptPlan() {
    if (!planResult) return;
    setApproval(planResult);
    setPlanResult(null);
  }

  function handleApproveStrategy(campaignName: string) {
    if (!sessionToken || !approval) return;
    const { campaigns, overallRecommendation, totalLeads } = approval;
    const selectedLeads = Array.from(selectedIndices).map((i) => leads[i]).filter(Boolean);
    saveCampaignApi(
      sessionToken,
      campaignName,
      "",
      totalLeads,
      { campaigns, overall_recommendation: overallRecommendation },
      "ready",
      selectedLeads,
    ).then(async (res) => {
      const saved = res.campaign as Record<string, unknown>;
      const cid = saved.id as string;
      setApproval(null);
      setPlanning(false);
      setGenerating({ campaignId: cid, campaignName });
      try {
        await generateCampaignDrafts(sessionToken, cid);
      } catch (err) {
        setGenerating(null);
        setError(err instanceof Error ? err.message : "Draft generation failed");
      }
    }).catch(() => {
      setApproval(null);
    });
  }

  function handleBackFromApproval() {
    if (!approval) return;
    setPlanResult(approval);
    setApproval(null);
  }

  function handleEditLater() {
    if (!approval) return;
    setApproval(null);
    setPlanning(false);
    clearSelection();
  }

  function handleCancelApproval() {
    setApproval(null);
    setPlanning(false);
    clearSelection();
  }

  function handleCustomizePlan() {
    /* Phase 2.5 — UI shell only */
  }

  function handleCancelPlan() {
    setPlanResult(null);
    setPlanning(false);
  }

  /* ── Batch Draft (for non-planner flow, legacy) ── */
  async function handleBatchDraft() {
    if (!sessionToken || selectedIndices.size === 0) return;
    const selectedLeads = Array.from(selectedIndices).map((i) => leads[i]).filter(Boolean);
    setBatchTotal(selectedLeads.length);
    setShowDraftNotification(false);

    try {
      const res = await batchDraftApi(sessionToken, selectedLeads);
      if (res.ok) {
        setBatchId(res.batch_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch draft failed");
    }
  }

  function handleBatchComplete() {
    setDraftsReady(batchTotal);
    setShowDraftNotification(true);
    setBatchId(null);
  }

  /* ── Save Campaign ── */
  function handleSaveCampaign() {
    setCampaignModal(true);
  }

  function handleCampaignSaved(name: string) {
    setCampaignModal(false);
  }

  /* ── Compare ── */
  function handleCompare() {
    if (selectedIndices.size >= 2) {
      setCompareOpen(true);
    }
  }

  /* ── Export ── */
  function handleExportCSV() {
    if (!sessionToken) return;
    const url = getExportCsvUrl(sessionToken);
    window.open(url, "_blank");
  }

  /* ── Existing campaigns for "Continue" prompt ── */
  const [existingCampaigns, setExistingCampaigns] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    if (!sessionToken) return;
    import("../../lib/api").then(({ getCampaignSummary }) => {
      getCampaignSummary(sessionToken).then((res) => {
        if (res.ok && Array.isArray(res.campaigns)) {
          setExistingCampaigns(res.campaigns.filter((c: Record<string, unknown>) => c.status !== "archived"));
        }
      }).catch(() => {});
    });
  }, [sessionToken]);

  const campaignTitle = leads.length > 0 ? "Lead Discovery Results" : "Lead Discovery Workspace";

  /* ── Campaign Planner View ── */
  if (planning) {
    return (
      <div className="flex h-full overflow-hidden">
        <section className="flex-1 overflow-y-auto">
          <PlannerLoading leadCount={selectedCount} />
        </section>
      </div>
    );
  }

  if (planResult) {
    return (
      <CampaignPlanner
        campaigns={planResult.campaigns}
        overallRecommendation={planResult.overallRecommendation}
        totalLeads={planResult.totalLeads}
        onAccept={handleAcceptPlan}
        onCustomize={handleCustomizePlan}
        onCancel={handleCancelPlan}
      />
    );
  }

  /* ── Generation Progress View ── */
  if (generating && sessionToken) {
    return (
      <GenerationProgress
        sessionToken={sessionToken}
        campaignId={generating.campaignId}
        campaignName={generating.campaignName}
        onComplete={() => {
          clearSelection();
        }}
        onError={(msg) => setError(msg)}
      />
    );
  }

  /* ── Approval View ── */
  if (approval) {
    return (
      <StrategyApproval
        campaigns={approval.campaigns}
        overallRecommendation={approval.overallRecommendation}
        totalLeads={approval.totalLeads}
        onApprove={handleApproveStrategy}
        onBack={handleBackFromApproval}
        onCancel={handleCancelApproval}
        onEditLater={handleEditLater}
      />
    );
  }

  /* ── Discovery View ── */
  return (
    <div className="flex h-full overflow-hidden">
      <section className="flex-1 overflow-y-auto px-6 pb-40 lg:pr-6">
        {/* Campaign Header */}
        <div className="mb-6 pt-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-headline-lg text-on-surface">{campaignTitle}</h2>
              {leads.length > 0 ? (
                <div className="flex items-center gap-4 mt-2">
                  <div className="bg-surface rounded-full h-2 w-48 overflow-hidden">
                    <div className="bg-primary h-full w-full rounded-full" />
                  </div>
                  <span className="text-on-surface-variant text-label-md">
                    {leads.length} {leads.length === 1 ? "lead" : "leads"} found
                    {selectedCount > 0 ? ` \u00b7 ${selectedCount} selected` : ""}
                  </span>
                </div>
              ) : null}
            </div>
            {leads.length > 0 && selectedCount === 0 ? (
              <button
                onClick={() => setSelectedIndices(new Set(leads.map((_, i) => i)))}
                className="text-sm text-primary font-medium hover:underline"
              >
                Select All
              </button>
            ) : null}
            {selectedCount > 0 && selectedCount < leads.length ? (
              <button
                onClick={() => setSelectedIndices(new Set(leads.map((_, i) => i)))}
                className="text-sm text-primary font-medium hover:underline"
              >
                Select All ({leads.length})
              </button>
            ) : null}
          </div>

          {/* Search bar */}
          <form onSubmit={handleSearch} className="flex gap-3">
            <div className="relative flex-1">
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Describe your service and target audience..."
                className="w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 pl-11 text-body-md text-on-surface outline-none placeholder:text-on-surface-variant/40 focus:border-primary/50"
              />
              <Icon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant/40" />
            </div>
            <button
              type="submit"
              disabled={searching || !searchQuery.trim()}
              className="inline-flex items-center justify-center rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-on-primary transition-all duration-150 hover:brightness-110 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
            >
              {searching ? (
                <>
                  <svg className="-ml-1 mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Searching...
                </>
              ) : "Search"}
            </button>
          </form>
        </div>

        {/* AI Status Bar (during search) */}
        {searching ? (
          <>
            <div className="bg-primary-container/10 border border-primary/20 rounded-xl px-4 py-3 flex items-center justify-between mb-6 animate-fade-in">
              <div className="flex items-center gap-3">
                <Icon name="auto_awesome" className="text-primary animate-pulse" />
                <p className="text-primary font-medium">
                  Researching leads...{" "}
                  <span className="text-on-surface-variant opacity-70">Scanning for best matches</span>
                </p>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-1 h-4 bg-primary animate-bounce" style={{ animationDelay: "0.1s" }} />
                <div className="w-1 h-4 bg-primary animate-bounce" style={{ animationDelay: "0.2s" }} />
                <div className="w-1 h-4 bg-primary animate-bounce" style={{ animationDelay: "0.3s" }} />
              </div>
            </div>
            <div className="space-y-3 animate-fade-in">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="rounded-xl border border-outline-variant/10 bg-surface-lowest p-4 flex items-center gap-4 animate-skeleton-pulse"
                  style={{ animationDelay: `${i * 0.08}s` }}>
                  <div className="w-10 h-10 rounded-lg bg-surface-high/50 shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-48 bg-surface-high/50 rounded-lg" />
                    <div className="h-3 w-32 bg-surface-high/50 rounded-lg" />
                  </div>
                  <div className="flex gap-2">
                    <div className="h-5 w-16 bg-surface-high/50 rounded-full" />
                    <div className="h-5 w-16 bg-surface-high/50 rounded-full" />
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Error */}
        {error ? (
          <div className="mb-6 rounded-xl border border-error/20 bg-error/5 px-4 py-3 text-sm text-error animate-scale-in">
            <div className="flex items-start gap-2.5">
              <Icon name="warning" className="text-error text-sm mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          </div>
        ) : null}

        {/* Batch progress */}
        {batchId && sessionToken ? (
          <div className="mb-6">
            <BatchProgress
              sessionToken={sessionToken}
              batchId={batchId}
              total={batchTotal}
              onComplete={handleBatchComplete}
              onError={setError}
            />
          </div>
        ) : null}

        {/* Drafts ready notification */}
        {showDraftNotification && draftsReady > 0 ? (
          <div className="mb-6 rounded-xl border border-secondary/20 bg-secondary/5 px-5 py-4 flex items-center justify-between animate-slide-up">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-secondary/20 flex items-center justify-center">
                <Icon name="edit_note" className="text-secondary" />
              </div>
              <div>
                <p className="font-bold text-on-surface">{draftsReady} {draftsReady === 1 ? "Draft" : "Drafts"} Ready</p>
                <p className="text-sm text-on-surface-variant">Generated and ready for review</p>
              </div>
            </div>
            <a
              href="/draft"
              className="px-5 py-2 bg-secondary text-on-primary font-bold rounded-lg hover:brightness-110 transition-all text-sm flex items-center gap-2"
            >
              Review Now
              <Icon name="arrow_forward" className="text-sm" />
            </a>
          </div>
        ) : null}

        {/* Empty state (searched but no results) */}
        {hasSearched && !searching && leads.length === 0 && !error && !batchId ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
              <Icon name="explore" className="text-4xl" />
            </div>
            <p className="text-body-lg text-on-surface-variant/60">No leads found</p>
            <p className="mt-1 text-body-md text-on-surface-variant/40">Try a different search query or broaden your targeting.</p>
          </div>
        ) : null}

        {/* Initial empty state */}
        {!hasSearched && !batchId ? (
          <div>
            {/* Continue existing campaigns */}
            {existingCampaigns.length > 0 ? (
              <div className="mb-8">
                <h3 className="text-label-sm text-on-surface-variant/40 uppercase tracking-wider font-medium mb-3">
                  Continue Existing Campaign
                </h3>
                <div className="space-y-2">
                  {existingCampaigns.slice(0, 3).map((c) => (
                    <a
                      key={c.id as string}
                      href={`/campaigns/${c.id}`}
                      className="group flex items-center justify-between card-interactive px-5 py-3.5"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-primary-container/10 flex items-center justify-center shrink-0">
                          <Icon name="campaign" className="text-primary text-sm" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-body-md text-on-surface font-bold truncate">
                            {c.name as string}
                          </p>
                          <p className="text-label-sm text-on-surface-variant/60">
                            {(c.pending_drafts as number) > 0
                              ? `${c.pending_drafts} draft${c.pending_drafts !== 1 ? "s" : ""} pending`
                              : `${c.lead_count as number} lead${c.lead_count !== 1 ? "s" : ""}`}
                          </p>
                        </div>
                      </div>
                      <span className="text-label-sm text-primary font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                        Continue
                      </span>
                    </a>
                  ))}
                  {existingCampaigns.length > 3 ? (
                    <a
                      href="/campaigns"
                      className="block text-center text-label-sm text-primary font-medium py-2 hover:underline"
                    >
                      View all {existingCampaigns.length} campaigns
                    </a>
                  ) : null}
                </div>
              </div>
            ) : null}

            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center text-primary mb-6">
                <Icon name="explore" className="text-5xl" />
              </div>
              <p className="text-headline-md text-on-surface/60 mb-2">Discover qualified leads</p>
              <p className="text-body-md text-on-surface-variant/40 max-w-md">
                Describe your ideal customer {"\u2014"} what industry, role, company size, or technology they use.
                Loqi will search and rank the best matches.
              </p>
            </div>
          </div>
        ) : null}

        {/* Lead Cards Grid */}
        {leads.length > 0 && !batchId ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {leads.map((lead, index) => (
              <LeadCard
                key={`${lead.lead_id || lead.id || index}`}
                lead={lead}
                index={index}
                selected={selectedIndices.has(index)}
                onToggle={toggleSelection}
              />
            ))}
          </div>
        ) : null}
      </section>

      {/* Compare Panel */}
      {compareOpen && selectedLeads.length >= 2 ? (
        <ComparePanel leads={selectedLeads} onClose={() => setCompareOpen(false)} />
      ) : null}

      {/* Save Campaign Modal */}
      {campaignModal && sessionToken ? (
        <SaveCampaignModal
          sessionToken={sessionToken}
          selectedCount={selectedCount}
          searchQuery={searchQuery}
          leads={selectedLeads}
          onClose={() => setCampaignModal(false)}
          onSaved={handleCampaignSaved}
        />
      ) : null}

      {/* Batch Action Bar */}
      {selectedCount > 0 && !batchId ? (
        <BatchActionBar
          count={selectedCount}
          onDraft={handlePlanCampaigns}
          onSaveCampaign={handleSaveCampaign}
          onCompare={handleCompare}
          onExport={handleExportCSV}
          onClear={clearSelection}
        />
      ) : null}
    </div>
  );
}
