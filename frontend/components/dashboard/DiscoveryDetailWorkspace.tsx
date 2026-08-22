"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { onServerEvent, type ServerEvent } from "../../lib/event-client";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import {
  fetchDiscovery,
  fetchDiscoveryFresh,
  peekCachedDiscovery,
  startDiscoverySearch,
} from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import { toast } from "../shared/Toast";
import { addLeadToCampaign, decideLead, listCampaigns } from "../../lib/api";
import {
  buildDiscoveryQuery,
  discoveryDetailUrl,
  parseDiscoveryMode,
} from "../../lib/discovery-mode";
import type {
  DiscoveryData,
  DiscoveryPlan,
  DiscoveryProgress,
  DiscoveryRecommendation,
  DiscoveryQualification,
} from "../../lib/domain";

const EXECUTION_STAGES = [
  "Initializing research",
  "Understanding target market",
  "Finding matching companies",
  "Ranking prospects",
  "Preparing recommendations",
];

function stageIndexFor(label: string | undefined): number {
  if (!label) return -1;
  return EXECUTION_STAGES.findIndex((stage) => label.startsWith(stage));
}

function DiscoveryExecutionPanel({
  progress,
  plan,
  narrative,
}: {
  progress?: DiscoveryProgress;
  plan?: DiscoveryPlan;
  narrative?: string;
}) {
  const stageIndex = stageIndexFor(progress?.stage);
  const derivedPct =
    stageIndex >= 0
      ? Math.round(((stageIndex + 1) / EXECUTION_STAGES.length) * 100)
      : 0;
  const pct = Math.min(100, Math.max(0, progress?.progress ?? derivedPct));
  const shownPct = Math.max(pct, 6);
  const currentLabel =
    stageIndex >= 0
      ? EXECUTION_STAGES[stageIndex]
      : progress?.stage || "Initializing research";

  return (
    <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-6 md:p-8 ambient-shadow animate-fade-in">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold truncate mr-3">
          {currentLabel}…
        </p>
        <span className="text-sm font-semibold text-primary tabular-nums shrink-0">
          {shownPct}%
        </span>
      </div>
      <div className="h-1.5 bg-surface-high/40 rounded-full overflow-hidden mb-8">
        <div
          className="h-full bg-primary rounded-full transition-all duration-700 ease-out"
          style={{ width: `${shownPct}%` }}
        />
      </div>
      <ol className="space-y-3.5">
        {EXECUTION_STAGES.map((stage, i) => {
          const done = i < stageIndex;
          const current = i === stageIndex || (stageIndex < 0 && i === 0);
          return (
            <li
              key={stage}
              className={`flex items-center gap-3 text-sm transition-colors ${
                done
                  ? "text-on-surface-variant/60"
                  : current
                    ? "text-on-surface font-medium"
                    : "text-on-surface-variant/40"
              }`}
            >
              {done ? (
                <span className="material-symbols-outlined text-[18px] text-primary/70">
                  check_circle
                </span>
              ) : current ? (
                <span className="material-symbols-outlined text-[18px] text-primary animate-spin">
                  autorenew
                </span>
              ) : (
                <span className="material-symbols-outlined text-[18px]">
                  radio_button_unchecked
                </span>
              )}
              <span>{stage}…</span>
            </li>
          );
        })}
      </ol>
      {(plan?.industries?.length || plan?.geography?.length) ? (
        <div className="flex flex-wrap gap-2 mt-8">
          {plan!.industries.slice(0, 4).map((industry) => (
            <span
              key={industry}
              className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium"
            >
              {industry}
            </span>
          ))}
          {plan!.geography.slice(0, 2).map((region) => (
            <span
              key={region}
              className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium"
            >
              {region}
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-8 text-sm text-on-surface-variant/50">{narrative}</p>
      )}
    </div>
  );
}

function PlanChipList({ items, max = 8 }: { items: string[]; max?: number }) {
  if (items.length === 0) return null;
  const shown = items.slice(0, max);
  const overflow = items.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((item, i) => (
        <span
          key={`${item}-${i}`}
          className="bg-surface-container px-2.5 py-1 rounded-md text-xs text-on-surface-variant"
        >
          {item}
        </span>
      ))}
      {overflow > 0 && (
        <span className="px-2 py-1 rounded-md text-xs text-on-surface-variant/50 font-medium">
          +{overflow} more
        </span>
      )}
    </div>
  );
}

function AtGlancePanel({ plan }: { plan?: DiscoveryPlan }) {
  if (!plan) return null;
  const facts: { label: string; content: React.ReactNode }[] = [];
  if (plan.targetAudience) {
    facts.push({ label: "Target audience", content: <p className="text-sm text-on-surface leading-relaxed">{plan.targetAudience}</p> });
  }
  if (plan.industries.length > 0 || plan.subIndustries.length > 0) {
    facts.push({ label: "Industries", content: <PlanChipList items={[...plan.industries, ...plan.subIndustries]} /> });
  }
  if (plan.geography.length > 0) {
    facts.push({ label: "Geography", content: <PlanChipList items={plan.geography} /> });
  }
  if (plan.decisionMakerRoles.length > 0 || plan.buyerPersonas.length > 0) {
    facts.push({ label: "Decision makers", content: <PlanChipList items={[...plan.decisionMakerRoles, ...plan.buyerPersonas]} max={4} /> });
  }
  if (plan.companySize.length > 0) {
    facts.push({ label: "Company size", content: <PlanChipList items={plan.companySize} /> });
  }
  if (plan.technologies.length > 0) {
    facts.push({ label: "Technologies", content: <PlanChipList items={plan.technologies} max={4} /> });
  }
  if (plan.buyingSignals.length > 0) {
    facts.push({ label: "Buying signals", content: <PlanChipList items={plan.buyingSignals} max={2} /> });
  }
  if (plan.painPoints.length > 0) {
    facts.push({ label: "Pain points", content: <PlanChipList items={plan.painPoints} max={2} /> });
  }
  if (facts.length === 0) return null;
  return (
    <aside className="min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 font-semibold mb-4">
        At a glance
      </p>
      <dl className="space-y-5">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 font-semibold mb-1.5">
              {fact.label}
            </dt>
            <dd>{fact.content}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}

function ExpandableRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <details className="group">
      <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden text-sm text-on-surface-variant/60 hover:text-primary transition-colors inline-flex items-center gap-1.5">
        <span className="material-symbols-outlined text-[16px] transition-transform group-open:rotate-90">
          chevron_right
        </span>
        {label}
      </summary>
      <div className="mt-4 pt-4 border-t border-outline-variant/10">{children}</div>
    </details>
  );
}

function QualificationEvidencePanel({ qualification }: { qualification?: DiscoveryQualification }) {
  if (!qualification) return null;
  const prospectEvidence = qualification.prospect_evidence || [];
  const icpMatch = qualification.structured_icp_match || {};
  const knowledge = qualification.knowledge_context || {};
  const strategic = qualification.strategic_observations || {};
  const hasContext = (knowledge.knowledge_item_ids || []).length > 0
    || (knowledge.knowledge_source_ids || []).length > 0
    || (strategic.strategic_update_ids || []).length > 0;
  if (prospectEvidence.length === 0 && !hasContext && (icpMatch.matched_roles || []).length === 0 && (icpMatch.matched_industries || []).length === 0) return null;

  return (
    <div className="mt-5 rounded-lg border border-outline-variant/20 bg-surface-container-low p-5">
      <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-4">Why this lead matched</h4>
      {prospectEvidence.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-semibold text-on-surface mb-2">Prospect evidence</p>
          <div className="space-y-1.5">{prospectEvidence.map((item) => <p key={`${item.field}-${item.value}`} className="text-xs text-on-surface-variant"><span className="font-medium text-on-surface">{item.field}:</span> {item.value}</p>)}</div>
        </div>
      )}
      {((icpMatch.matched_roles || []).length > 0 || (icpMatch.matched_industries || []).length > 0) && (
        <div className="mb-4">
          <p className="text-xs font-semibold text-on-surface mb-2">Structured ICP match</p>
          <p className="text-xs leading-relaxed text-on-surface-variant">{[...(icpMatch.matched_roles || []).map((value) => `Role matches ${value}`), ...(icpMatch.matched_industries || []).map((value) => `Industry matches ${value}`)].join(" · ")}</p>
          {(icpMatch.influenced_dimensions || []).length > 0 && <p className="mt-1 text-[11px] text-on-surface-variant/50">Dimension: {(icpMatch.influenced_dimensions || []).join(", ")}</p>}
        </div>
      )}
      {((knowledge.knowledge_item_ids || []).length > 0 || (knowledge.knowledge_source_ids || []).length > 0) && (
        <div className="mb-4">
          <p className="text-xs font-semibold text-on-surface mb-2">Knowledge context <span className="font-normal text-on-surface-variant/50">(guidance, not prospect evidence)</span></p>
          <p className="text-xs text-on-surface-variant">Fields: {(knowledge.contributed_fields || []).join(", ") || "business context"}</p>
          <p className="mt-1 text-[11px] text-on-surface-variant/50">Items: {(knowledge.knowledge_item_ids || []).join(", ") || "none"} · Sources: {(knowledge.knowledge_source_ids || []).join(", ") || "none"}</p>
        </div>
      )}
      {(strategic.strategic_update_ids || []).length > 0 && (
        <div>
          <p className="text-xs font-semibold text-on-surface mb-2">Strategic observations <span className="font-normal text-on-surface-variant/50">(observations, not prospect facts)</span></p>
          {(strategic.observations || []).map((item) => <p key={item.id} className="text-xs leading-relaxed text-on-surface-variant">{item.title || item.id}: {item.observation}</p>)}
          <p className="mt-1 text-[11px] text-on-surface-variant/50">Update IDs: {(strategic.strategic_update_ids || []).join(", ")}</p>
        </div>
      )}
    </div>
  );
}

function ResearchPlan({ plan, embedded = false }: { plan?: DiscoveryPlan; embedded?: boolean }) {
  if (!plan) return null;
  const rows: { label: string; values: string[] }[] = [];
  if (plan.offering || plan.primaryServices.length > 0) {
    rows.push({
      label: "What you're offering",
      values: [plan.offering, ...plan.primaryServices].filter(Boolean),
    });
  }
  if (plan.targetAudience) {
    rows.push({ label: "Target audience", values: [plan.targetAudience] });
  }
  if (plan.industries.length > 0 || plan.subIndustries.length > 0) {
    rows.push({
      label: "Industries",
      values: [...plan.industries, ...plan.subIndustries].filter(Boolean),
    });
  }
  if (plan.icpSummary) {
    rows.push({ label: "Ideal customer profile", values: [plan.icpSummary] });
  }
  if (plan.buyerPersonas.length > 0 || plan.decisionMakerRoles.length > 0) {
    rows.push({
      label: "Decision makers",
      values: [...plan.buyerPersonas, ...plan.decisionMakerRoles].filter(Boolean),
    });
  }
  if (plan.companyKeywords.length > 0) {
    rows.push({ label: "Company signals", values: plan.companyKeywords });
  }
  if (plan.buyingSignals.length > 0) {
    rows.push({ label: "Buying signals", values: plan.buyingSignals });
  }
  if (plan.painPoints.length > 0) {
    rows.push({ label: "Pain points", values: plan.painPoints });
  }
  if (plan.geography.length > 0) {
    rows.push({ label: "Geography", values: plan.geography });
  }
  if (plan.companySize.length > 0) {
    rows.push({ label: "Company size", values: plan.companySize });
  }
  if (plan.technologies.length > 0) {
    rows.push({ label: "Technologies", values: plan.technologies });
  }
  if (plan.negativeKeywords.length > 0) {
    rows.push({ label: "Negative keywords", values: plan.negativeKeywords });
  }
  if (plan.exclusions.length > 0) {
    rows.push({ label: "Exclusions", values: plan.exclusions });
  }
  if (plan.messagingAngle) {
    rows.push({ label: "Messaging angle", values: [plan.messagingAngle] });
  }
  if (plan.successCriteria) {
    rows.push({ label: "Success criteria", values: [plan.successCriteria] });
  }
  if (rows.length === 0) return null;
  if (embedded) {
    return (
      <dl className="grid md:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-5">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 font-semibold mb-1.5">
              {row.label}
            </dt>
            <dd className="text-sm text-on-surface leading-relaxed">{row.values.join(" · ")}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <section className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-6 md:p-8 ambient-shadow">
      <h2 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-6">
        How I'm running this research
      </h2>
      <dl className="grid md:grid-cols-2 gap-x-8 gap-y-5">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 font-semibold mb-1.5">
              {row.label}
            </dt>
            <dd className="text-sm text-on-surface leading-relaxed">{row.values.join(" · ")}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

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
            <span className="block text-lg font-serif text-on-surface">{rec.company}</span>
            <span className="block text-[11px] uppercase tracking-wider text-on-surface-variant/60 mt-1">{rec.subtitle}</span>
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
            <QualificationEvidencePanel qualification={rec.qualification} />
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

export default function DiscoveryDetailWorkspace({ discoveryId }: { discoveryId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const parsed = useMemo(() => parseDiscoveryMode(searchParams), [searchParams]);
  const attachContext = parsed.mode === "campaign_attach" ? parsed.context : null;
  const campaignId = attachContext?.campaignId || "";
  const attachMode = !!campaignId;
  const [linkedCampaign, setLinkedCampaign] = useState<{ id: string; name: string } | null>(null);
  const fetcher = useCallback(() => fetchDiscovery(discoveryId), [discoveryId]);
  const { data, loading, error, retry } = useData(fetcher, {
    initial: peekCachedDiscovery(discoveryId),
  });
  const [live, setLive] = useState<DiscoveryData | null>(null);
  const view = live ?? data;
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [selectedLeads, setSelectedLeads] = useState<Map<string, DiscoveryRecommendation>>(new Map());
  const [expandedLead, setExpandedLead] = useState<string | null>(null);
  const [savingSelection, setSavingSelection] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const tellLoqi = useTellLoqi("Discovery", {
    recommendations: view?.recommendations.length ?? 0,
  });

  useEffect(() => {
    if (campaignId) return;
    let cancelled = false;
    const token = (() => {
      try { return localStorage.getItem("loqi_active_session_token"); }
      catch { return null; }
    })();
    if (!token || !discoveryId) return;
    listCampaigns(token)
      .then((res) => {
        if (cancelled || !res?.ok || !Array.isArray(res.campaigns)) return;
        const owner = res.campaigns.find(
          (c) => String((c as Record<string, unknown>).discovery_id || "") === discoveryId,
        );
        if (owner) {
          setLinkedCampaign({
            id: String(owner.id || ""),
            name: String(owner.name || "the campaign"),
          });
        }
      })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, [campaignId, discoveryId]);

  useEffect(() => {
    const status = live?.status ?? data?.status;
    console.log("[kickoff] DiscoveryDetailWorkspace: mount", {
      discoveryId,
      status: status || "(unknown)",
      fromCache: !!peekCachedDiscovery(discoveryId),
    });
    if (!status || (status !== "searching" && status !== "queued")) return;
    console.log("[kickoff] DiscoveryDetailWorkspace: starting poll loop for", discoveryId);
    let cancelled = false;
    // PR-P1.4: in-flight guard — discovery polls must not overlap when a
    // request outlives the 4s interval.
    let pollBusy = false;
    const poll = async () => {
      if (cancelled || pollBusy) return;
      pollBusy = true;
      try {
        const fresh = await fetchDiscoveryFresh(discoveryId);
        console.log(
          "[kickoff] DiscoveryDetailWorkspace: poll tick",
          fresh ? { status: fresh.status, companies: fresh.companyCount, leads: fresh.leadCount } : "(null)",
        );
        if (!cancelled && fresh) setLive(fresh);
      } catch {
        /* transient — the next tick retries */
      } finally {
        pollBusy = false;
      }
    };
    // PR-3D: event-driven refresh — the SSE stream triggers an immediate
    // authoritative refetch on every job event for THIS discovery. The
    // interval remains only as a slow safety net for missed pub/sub events
    // (ephemeral transport), reduced from 4s to 15s.
    const offEvent = onServerEvent((event: ServerEvent) => {
      if (cancelled) return;
      const ed = (event.data as Record<string, unknown> | undefined)?.discovery_id;
      if (ed && ed !== discoveryId) return;
      if (event.type === "job.progress" || event.type === "job.completed") {
        void poll();
      }
    });
    void poll();
    const id = window.setInterval(poll, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      offEvent();
    };
  }, [discoveryId, live?.status, data?.status]);

  const rerunDiscovery = async () => {
    const contextQuery = attachContext ? buildDiscoveryQuery(attachContext) : "";
    const query = contextQuery || (view?.query || "").trim();
    if (!query) {
      toast("error", "No target to research again");
      return;
    }
    setRestarting(true);
    try {
      const started = await startDiscoverySearch(query);
      if (started?.discoveryId) {
        router.push(discoveryDetailUrl(started.discoveryId, attachContext));
      } else {
        toast("error", "Could not restart the discovery");
      }
    } catch {
      toast("error", "Could not restart the discovery");
    } finally {
      setRestarting(false);
    }
  };

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
        router.push(`/campaigns/new?return=discovery&discovery=${encodeURIComponent(discoveryId)}`);
        return;
      }
      const results = await Promise.all(leads.map((rec) => addLeadToCampaign(token, campaignId, leadPayload(rec), discoveryId)));
      const successful = results.filter((result) => result.ok);
      const failed = results.length - successful.length;
      if (failed > 0) throw new Error(`${failed} lead${failed === 1 ? "" : "s"} could not be added`);
      const added = successful.filter((result) => result.added).length;
      toast("success", `${added} lead${added === 1 ? "" : "s"} attached to the campaign`);
      setSelectedLeads(new Map());
      try {
        sessionStorage.removeItem(`loqi_attach_started_${campaignId}`);
      } catch {
        /* non-fatal */
      }
      router.push(`/campaigns/${encodeURIComponent(campaignId)}`);
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

  const visible = view?.recommendations.filter((r) => !dismissed.has(r.id)) ?? [];

  const attachTarget =
    attachContext?.objective || attachContext?.audience || attachContext?.campaignName || "";
  const researchTitle =
    attachMode && (view?.status === "searching" || view?.status === "queued")
      ? `Researching prospects for ${attachTarget || "this campaign"}...`
      : null;

  const returnCampaignId = campaignId || linkedCampaign?.id || "";
  const historyLink = useMemo(() => {
    if (returnCampaignId) {
      return (
        <button
          type="button"
          onClick={() => router.push(`/campaigns/${encodeURIComponent(returnCampaignId)}`)}
          className="inline-flex items-center gap-1.5 text-sm text-on-surface-variant/60 hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-[16px]">arrow_back</span>
          Return to campaign{linkedCampaign?.name ? `: ${linkedCampaign.name}` : ""}
        </button>
      );
    }
    return (
      <button
        type="button"
        onClick={() => router.push("/discovery")}
        className="inline-flex items-center gap-1.5 text-sm text-on-surface-variant/60 hover:text-primary transition-colors"
      >
        <span className="material-symbols-outlined text-[16px]">arrow_back</span>
        All discoveries
      </button>
    );
  }, [returnCampaignId, linkedCampaign?.name, router]);

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <div className="space-y-6 animate-fade-in">
              {historyLink}
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

  if (!view || view.recommendations.length === 0) {
    const running = view?.status === "searching" || view?.status === "queued";
    const failed = view?.status === "failed" || view?.status === "cancelled";
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <section className="space-y-6 animate-fade-in">
              {historyLink}
              <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
                {researchTitle || (view ? view.narrativeTitle : "Market Discovery")}
              </h1>
              <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light">
                {view?.narrativeLines?.[0] || "Tell me what market you want to explore and I will research companies that match your ideal customer profile."}
              </p>
            </section>
            {running ? (
              <section className="space-y-6 animate-fade-in">
                <DiscoveryExecutionPanel
                  progress={view?.progress}
                  plan={view?.plan}
                  narrative={view?.narrativeLines?.[1]}
                />
              </section>
            ) : failed ? (
              <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
                <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                  <span className="material-symbols-outlined text-3xl">search_off</span>
                </div>
                <p className="text-body-lg text-on-surface-variant/80 font-medium">
                  Nothing was found this time
                </p>
                <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                  The run stopped before completing. Restart it and I will derive a fresh plan from the same target.
                </p>
                <button
                  type="button"
                  disabled={restarting}
                  onClick={() => void rerunDiscovery()}
                  className="mt-6 bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {restarting ? "Running…" : "Run again"}
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
                <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                  <span className="material-symbols-outlined text-3xl">explore</span>
                </div>
                <p className="text-body-lg text-on-surface-variant/80 font-medium">
                  No recommendations yet
                </p>
                <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                  Describe your target market and I will surface high-conviction prospects.
                </p>
              </div>
            )}
            {view && !running && !failed && view.plan && <ResearchPlan plan={view.plan} />}
            {!running && !attachMode && (
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
              </section>
            )}
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="py-16 flex flex-col gap-16">

          {/* Section 0: breadcrumb */}
          <section className="reading-column animate-fade-in">{historyLink}</section>

          {/* Section 1: Executive Research Briefing (full width) */}
          <section className="w-full px-4 md:px-6 lg:px-10 animate-fade-in">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl overflow-hidden ambient-shadow">
              <div className="flex items-center justify-between gap-3 px-6 md:px-8 py-4 border-b border-outline-variant/20">
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    <span className="material-symbols-outlined text-[16px]">insights</span>
                  </span>
                  <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 font-semibold truncate">
                    Executive Research Briefing
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium">
                    {view.companyCount} companies
                  </span>
                  {view.leadCount > 0 && (
                    <span className="bg-secondary-container text-on-secondary-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider font-medium">
                      {view.leadCount} decision makers
                    </span>
                  )}
                </div>
              </div>
              <div className="grid lg:grid-cols-3 gap-8 px-6 md:px-8 py-6 md:py-8">
                <div className="lg:col-span-2 min-w-0 space-y-4">
                  <h1 className="text-3xl md:text-4xl font-serif text-on-surface leading-tight tracking-tight font-normal">
                    {view.narrativeTitle}
                  </h1>
                  {view.narrativeLines[0] && (
                    <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light line-clamp-2">
                      {view.narrativeLines[0]}
                    </p>
                  )}
                  {view.narrativeLines.length > 1 && (
                    <ExpandableRow label="Read the full research narrative">
                      <div className="space-y-3">
                        {view.narrativeLines.slice(1).map((line, i) => (
                          <p key={i} className="text-sm text-on-surface-variant/70 leading-relaxed font-light">
                            {line}
                          </p>
                        ))}
                      </div>
                    </ExpandableRow>
                  )}
                  {view.plan && (
                    <ExpandableRow label="How this research was planned">
                      <ResearchPlan plan={view.plan} embedded />
                    </ExpandableRow>
                  )}
                </div>
                <AtGlancePanel plan={view.plan} />
              </div>
            </div>
          </section>

          {/* Section 2: Research Toolbar & Filters */}
          <div className="reading-column flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-outline-variant/20 pb-6">
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-on-surface-variant/50 font-medium">Active Filters:</span>
              <div className="flex gap-2">
                {view.filters.map((f) => (
                  <span
                    key={f.id}
                    className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium"
                  >
                    {f.label}
                  </span>
                ))}
                {view.filters.length === 0 && (
                  <span className="text-sm text-on-surface-variant/50">Sourced from matching this market</span>
                )}
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
                  {savingSelection ? "Attaching…" : returnCampaignId ? `Attach ${selectedLeads.size} lead${selectedLeads.size === 1 ? "" : "s"} to Campaign` : `Create Campaign with ${selectedLeads.size}`}
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

          {/* Section 3: Recommended Companies Stack (full-width) */}
          <div className="w-full px-6 md:px-10">
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
          </div>

          {/* Section 4: Tell Loqi (hidden in attach mode — research is driven by the campaign) */}
          {!attachMode && (
            <section className="reading-column pt-6 border-t border-outline-variant/20">
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
          )}

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
