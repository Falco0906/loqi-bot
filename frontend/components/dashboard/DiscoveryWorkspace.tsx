"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import { fetchDiscovery, peekCachedDiscovery } from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import { toast } from "../shared/Toast";
import { addLeadToCampaign, decideLead } from "../../lib/api";
import type { DiscoveryRecommendation } from "../../lib/domain";

function RecommendationCard({
  rec,
  selected,
  expanded,
  onDismiss,
  onToggle,
  onExpand,
}: {
  rec: DiscoveryRecommendation;
  selected: boolean;
  expanded: boolean;
  onDismiss: () => void;
  onToggle: (rec: DiscoveryRecommendation) => void;
  onExpand: () => void;
}) {
  return (
    <article className={`border-b border-outline-variant/20 transition-colors ${expanded ? "bg-surface-lowest shadow-lg" : "hover:bg-surface-container-low"}`}>
      <div className="grid grid-cols-12 gap-3 md:gap-4 px-4 md:px-6 py-5 items-center">
        <button type="button" onClick={onExpand} className="col-span-5 md:col-span-4 flex items-center gap-3 text-left min-w-0">
          <span className={`material-symbols-outlined text-on-surface-variant/50 transition-transform ${expanded ? "rotate-180" : ""}`}>expand_more</span>
          <span className="min-w-0">
            <span className="block text-lg font-serif text-on-surface truncate">{rec.company}</span>
            <span className="block text-[11px] uppercase tracking-wider text-on-surface-variant/60 truncate mt-1">{rec.subtitle}</span>
          </span>
        </button>
        <div className="col-span-2 text-center"><span className="bg-secondary-container text-on-secondary-container px-2 py-1 rounded text-xs font-medium">{rec.match}%</span></div>
        <div className="hidden md:block md:col-span-2 text-sm text-on-surface-variant">{rec.stage}</div>
        <div className="hidden md:block md:col-span-2 text-sm text-on-surface-variant">{rec.location}</div>
        <div className="col-span-5 md:col-span-2 flex justify-end gap-3 items-center">
          <button type="button" onClick={() => onToggle(rec)} className={`px-3 py-1.5 rounded-full text-xs font-semibold ${selected ? "bg-primary text-on-primary" : "border border-outline-variant text-on-surface-variant hover:text-primary"}`}>
            {selected ? "Selected" : "Select"}
          </button>
          <button type="button" onClick={onDismiss} className="material-symbols-outlined text-on-surface-variant/60 hover:text-error" title="Ignore">block</button>
        </div>
      </div>
      {expanded && (
        <div className="px-8 md:px-14 pb-8 pt-2 grid md:grid-cols-5 gap-8">
          <div className="md:col-span-3">
            <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-3">Executive Deep Reasoning</h4>
            <p className="text-sm text-on-surface-variant leading-relaxed mb-5">{rec.reasoning}</p>
            <div className="p-5 rounded-lg bg-surface-container-low border border-outline-variant/20">
              <p className="text-xs uppercase tracking-wider font-semibold text-on-surface mb-2">Key buying signal</p>
              <p className="text-sm font-medium text-on-surface">{rec.buyingSignal}</p>
              <p className="text-sm text-on-surface-variant/70 mt-1">{rec.signalDetail}</p>
            </div>
          </div>
          <div className="md:col-span-2 space-y-5">
            <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold">Research Evidence</h4>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between border-b border-outline-variant/20 pb-2"><span className="text-on-surface-variant">Funding history</span><span>{rec.funding}</span></div>
              <div className="flex justify-between border-b border-outline-variant/20 pb-2"><span className="text-on-surface-variant">Hiring trends</span><span>{rec.hiring}</span></div>
            </div>
            <button type="button" onClick={() => onToggle(rec)} className="border border-outline-variant px-5 py-2 rounded-full text-sm font-medium hover:bg-surface-container-low">
              {selected ? "Remove from selection" : "Select for campaign"}
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-16">
      {[1, 2].map((i) => (
        <div key={i} className="bg-surface-lowest rounded-xl p-8 md:p-10 border border-outline-variant/10 animate-skeleton-pulse">
          <div className="flex justify-between mb-8">
            <div className="space-y-3">
              <div className="h-6 w-48 bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-32 bg-surface-high/50 rounded-lg" />
            </div>
            <div className="flex gap-2">
              <div className="h-6 w-16 bg-surface-high/50 rounded-full" />
              <div className="h-6 w-20 bg-surface-high/50 rounded-full" />
            </div>
          </div>
          <div className="h-px bg-outline-variant/20 mb-8" />
          <div className="grid md:grid-cols-5 gap-8">
            <div className="md:col-span-3 space-y-4">
              <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-5/6 bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-4/6 bg-surface-high/50 rounded-lg" />
            </div>
            <div className="md:col-span-2 space-y-4">
              <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-3/4 bg-surface-high/50 rounded-lg" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DiscoveryWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const campaignId = searchParams?.get("campaign") || "";
  const { data, loading, error, retry } = useData(fetchDiscovery, {
    initial: peekCachedDiscovery(),
  });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [selectedLeads, setSelectedLeads] = useState<Map<string, DiscoveryRecommendation>>(new Map());
  const [expandedLead, setExpandedLead] = useState<string | null>(null);
  const [savingSelection, setSavingSelection] = useState(false);
  const tellLoqi = useTellLoqi("Discovery", {
    recommendations: data?.recommendations.length ?? 0,
  });

  const leadPayload = (rec: DiscoveryRecommendation) => ({
    id: rec.id, company: rec.company, title: rec.subtitle,
    seniority: rec.stage, location: rec.location,
    buying_signal: rec.buyingSignal, buying_signal_detail: rec.signalDetail,
  });

  const toggleLead = (rec: DiscoveryRecommendation) => {
    setSelectedLeads((previous) => {
      const next = new Map(previous);
      if (next.has(rec.id)) next.delete(rec.id);
      else next.set(rec.id, rec);
      return next;
    });
  };

  const commitSelectedLeads = async () => {
    if (selectedLeads.size === 0) return;
    const token = localStorage.getItem("loqi_active_session_token");
    if (!token) { toast("error", "Your workspace session is not ready yet"); return; }
    const leads = Array.from(selectedLeads.values());
    setSavingSelection(true);
    try {
      const decisions = await Promise.all(
        leads.map((rec) => decideLead(token, leadPayload(rec), true)),
      );
      if (decisions.some((result) => !result.ok)) {
        throw new Error("One or more lead approvals could not be persisted");
      }
      if (!campaignId) {
        sessionStorage.setItem("loqi_pending_campaign_leads", JSON.stringify(leads.map(leadPayload)));
        router.push("/campaigns/new?return=discovery");
        return;
      }
      const results = await Promise.all(leads.map((rec) => addLeadToCampaign(token, campaignId, leadPayload(rec))));
      const successful = results.filter((result) => result.ok);
      const failed = results.length - successful.length;
      if (failed > 0) throw new Error(`${failed} lead${failed === 1 ? "" : "s"} could not be added`);
      const added = successful.filter((result) => result.added).length;
      toast("success", `${added} lead${added === 1 ? "" : "s"} added to the campaign`);
      setSelectedLeads(new Map());
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Leads were not added to the campaign");
    } finally {
      setSavingSelection(false);
    }
  };

  const rejectLead = async (rec: DiscoveryRecommendation) => {
    const token = localStorage.getItem("loqi_active_session_token");
    if (!token) {
      toast("error", "Your workspace session is not ready yet");
      return;
    }
    try {
      const result = await decideLead(token, leadPayload(rec), false);
      if (!result.ok) throw new Error("Lead rejection was not persisted");
      setDismissed((previous) => new Set(previous).add(rec.id));
      setSelectedLeads((previous) => {
        const next = new Map(previous);
        next.delete(rec.id);
        return next;
      });
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Lead rejection failed");
    }
  };

  const visible = data?.recommendations.filter((r) => !dismissed.has(r.id)) ?? [];

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <div className="space-y-6 animate-fade-in">
              <div className="h-12 w-3/4 bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
              <div className="h-4 w-full bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
            </div>
            <LoadingSkeleton />
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 text-center">
            <p className="text-lg text-error mb-4">{error}</p>
            <button
              onClick={retry}
              className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Retry
            </button>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (!data || data.recommendations.length === 0) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <section className="space-y-6 animate-fade-in">
              <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
                Market Discovery
              </h1>
              <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light">
                Tell me what market you want to explore and I will research companies that match your ideal customer profile.
              </p>
            </section>
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <span className="material-symbols-outlined text-3xl">explore</span>
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No recommendations yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                Describe your target market and I will surface high-conviction prospects.
              </p>
            </div>
            <section className="pt-6 border-t border-outline-variant/20">
              <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
                <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                  Tell Loqi...
                </label>
                <div className="flex items-end gap-3 px-2 pb-1">
                  <textarea
                    className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                    placeholder="Research a different market..."
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
                  onClick={() => void tellLoqi.submit("Find Series A fintech companies in cross-border payments.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  FIND SERIES A FINTECH
                </button>
                <button
                  type="button"
                  onClick={() => void tellLoqi.submit("Shift focus to healthcare SaaS companies.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  SHIFT TO HEALTHCARE
                </button>
              </div>
            </section>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Section 1: Opening Narrative Briefing */}
          <section className="space-y-6 animate-fade-in">
            <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
              {data.narrativeTitle}
            </h1>
            <div className="space-y-4">
              {data.narrativeLines.map((line, i) => (
                <p key={i} className="text-lg text-on-surface-variant/60 leading-relaxed font-light">
                  {line}
                </p>
              ))}
            </div>
          </section>

          {/* Section 2: Research Toolbar & Filters */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-outline-variant/20 pb-6">
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-on-surface-variant/50 font-medium">Active Filters:</span>
              <div className="flex gap-2">
                {data.filters.map((f) => (
                  <span
                    key={f.id}
                    className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium"
                  >
                    {f.label}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex gap-4">
              {selectedLeads.size > 0 && (
                <button
                  type="button"
                  disabled={savingSelection}
                  onClick={() => void commitSelectedLeads()}
                  className="bg-primary text-on-primary px-5 py-2 rounded-full text-sm font-medium disabled:opacity-50"
                >
                  {savingSelection ? "Saving…" : campaignId ? `Add ${selectedLeads.size} to Campaign` : `Create Campaign with ${selectedLeads.size}`}
                </button>
              )}
              <button className="flex items-center gap-1 text-sm text-on-surface-variant/60 hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-[18px]">filter_list</span>
                Industry
              </button>
              <button className="flex items-center gap-1 text-sm text-on-surface-variant/60 hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-[18px]">tune</span>
                Status
              </button>
            </div>
          </div>

          {/* Section 3: Recommended Companies Stack */}
          <div className="w-full bg-surface-lowest border border-outline-variant/20 rounded-xl overflow-hidden shadow-sm">
            <div className="grid grid-cols-12 gap-3 md:gap-4 px-4 md:px-6 py-4 bg-surface-container-low border-b border-outline-variant/20 text-[10px] uppercase tracking-widest text-on-surface-variant/60 font-semibold">
              <div className="col-span-5 md:col-span-4">Company</div>
              <div className="col-span-2 text-center">Match</div>
              <div className="hidden md:block md:col-span-2">Stage</div>
              <div className="hidden md:block md:col-span-2">Location</div>
              <div className="col-span-5 md:col-span-2 text-right">Selection</div>
            </div>
            {visible.length === 0 && (
              <p className="text-lg text-on-surface-variant/40 italic text-center py-12">
                All recommendations reviewed. Tell me where to look next.
              </p>
            )}

            {visible.map((rec) => (
              <RecommendationCard
                key={rec.id}
                rec={rec}
                selected={selectedLeads.has(rec.id)}
                expanded={expandedLead === rec.id}
                onToggle={toggleLead}
                onExpand={() => setExpandedLead((current) => current === rec.id ? null : rec.id)}
                onDismiss={() => void rejectLead(rec)}
              />
            ))}
          </div>

          {/* Section 4: Tell Loqi */}
          <section className="pt-6 border-t border-outline-variant/20">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="Research a different market..."
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
                onClick={() => void tellLoqi.submit("Find Series A fintech companies in cross-border payments.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                FIND SERIES A FINTECH
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Shift focus to healthcare SaaS companies.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                SHIFT TO HEALTHCARE
              </button>
            </div>
          </section>

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
