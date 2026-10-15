"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import DiscoveryCampaignActions from "../../../components/dashboard/DiscoveryCampaignActions";
import {
  DiscoveryExecutionPanel,
  DiscoveryLeadDetails,
  DiscoveryResearchBriefing,
} from "../../../components/dashboard/DiscoveryDetailWorkspace";
import { useBetaFeature } from "../../../contexts/BetaFeaturesContext";
import { listWorkspaceLeads, TimeoutError, type WorkspaceLeadRecord } from "../../../lib/api";
import { parseDiscoveryMode } from "../../../lib/discovery-mode";
import { terminalDiscoveryMessage } from "../../../lib/discovery-status";
import { useIntelligenceWorkspace } from "../../../hooks/useIntelligenceWorkspace";
import { getNavState, setNavState } from "../../../lib/nav-state";
import { DISCOVERY_CONTEXT_KEY, discoverySelectionScope, discoveryResponseIsCurrent, discoverySavedFilters, rememberDiscoveryContext, restoredDiscoveryContext } from "../../../lib/discovery-context";
import {
  fetchDiscoveryFresh,
  fetchDiscoveryListFresh,
  startDiscoverySearch,
  workspaceLeadToRecommendation,
} from "../../../lib/repositories";
import type { DiscoveryData, DiscoveryProgress, DiscoveryRecommendation } from "../../../lib/domain";

const PAGE_SIZE = 50;
const FILTERS = [
  { key: "location", label: "Location", placeholder: "e.g. United States" },
  { key: "industry", label: "Industry", placeholder: "e.g. SaaS" },
  { key: "company", label: "Company", placeholder: "e.g. Acme" },
  { key: "title", label: "Job title", placeholder: "e.g. Head of Sales" },
  { key: "keywords", label: "Keywords", placeholder: "e.g. operations" },
] as const;

const SUGGESTIONS = [
  "Find SaaS founders in the US",
  "Find heads of sales at growing startups",
  "Find operations leaders at e-commerce companies",
];

function activeSessionToken(): string {
  return window.localStorage.getItem("loqi_active_session_token") || "";
}

function forgetRememberedDiscovery(): void {
  try {
    window.sessionStorage.removeItem(DISCOVERY_CONTEXT_KEY);
  } catch {
    // See rememberDiscovery.
  }
}

function FilterRail({
  workspaceId,
  filters,
  hasFilters,
  onChange,
  onClear,
  disabled,
}: {
  workspaceId: string;
  filters: Record<string, string>;
  hasFilters: boolean;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
  disabled: boolean;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-y-auto border-r border-outline-variant/15 bg-surface-lowest px-4 py-5 lg:w-[304px] lg:shrink-0">
      <div className="mb-5 flex items-center justify-between px-1">
        <h1 className="text-sm font-semibold text-on-surface">Filters</h1>
        <button
          type="button"
          disabled={!hasFilters || disabled}
          onClick={onClear}
          className="text-xs font-medium text-primary disabled:text-on-surface-variant/35"
        >
          Clear all
        </button>
      </div>
      <div className="border-y border-outline-variant/15">
        {FILTERS.map((filter) => {
          const open = expanded === filter.key;
          return (
            <div key={filter.key} className="border-b border-outline-variant/15 last:border-b-0">
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : filter.key)}
                className="flex w-full items-center justify-between gap-3 px-1 py-3 text-left text-sm text-on-surface transition-colors hover:text-primary"
              >
                <span>{filter.label}</span>
                <span className="material-symbols-outlined text-[18px]">
                  {open ? "expand_less" : "expand_more"}
                </span>
              </button>
              {open && (
                <div className="pb-3">
                  <input
                    aria-label={`Filter by ${filter.label}`}
                    value={filters[filter.key] || ""}
                    disabled={disabled}
                    placeholder={filter.placeholder}
                    onChange={(event) => onChange(filter.key, event.target.value)}
                    className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40 focus:border-primary/50"
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
      <Link
        href={`/discovery/history?workspace_id=${encodeURIComponent(workspaceId)}`}
        className="mt-auto flex items-center justify-between border-t border-outline-variant/15 px-1 pt-5 text-left text-sm text-on-surface-variant transition-colors hover:text-primary"
      >
        <span>Search history</span>
        <span className="material-symbols-outlined text-[18px]">history</span>
      </Link>
    </aside>
  );
}

function LeadResultsTable({
  leads,
  selected,
  selectedOnPage,
  expandedLeadId,
  detailsByLeadId,
  onToggleVisible,
  onToggleLead,
  onToggleExpand,
  disabled,
}: {
  leads: WorkspaceLeadRecord[];
  selected: Set<string>;
  selectedOnPage: boolean;
  expandedLeadId: string | null;
  detailsByLeadId: Map<string, DiscoveryRecommendation>;
  onToggleVisible: () => void;
  onToggleLead: (leadId: string) => void;
  onToggleExpand: (leadId: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-outline-variant/20 bg-surface-lowest">
      <table className="w-full min-w-[900px] text-left text-sm">
        <thead className="border-b border-outline-variant/20 bg-surface-container-low text-xs uppercase tracking-wider text-on-surface-variant/65">
          <tr>
            <th className="w-12 px-4 py-3">
              <input
                aria-label="Select all visible leads"
                type="checkbox"
                disabled={disabled}
                checked={selectedOnPage}
                onChange={onToggleVisible}
              />
            </th>
            <th className="px-3 py-3 font-medium">Person</th>
            <th className="px-3 py-3 font-medium">Company</th>
            <th className="px-3 py-3 font-medium">Title</th>
            <th className="px-3 py-3 font-medium">Location</th>
            <th className="px-3 py-3 font-medium">Industry</th>
            <th className="px-3 py-3 font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const name = `${lead.first_name} ${lead.last_name}`.trim();
            const expanded = expandedLeadId === lead.id;
            const details = detailsByLeadId.get(lead.id);
            return (
              <Fragment key={lead.id}>
                <tr className={`border-b border-outline-variant/10 transition-colors hover:bg-surface-container-low/55 ${expanded ? "bg-surface-container-low/40" : ""}`}>
                  <td className="px-4 py-3">
                    <input
                      aria-label={`Select ${name || lead.email || "lead"}`}
                      type="checkbox"
                      disabled={disabled}
                      checked={selected.has(lead.id)}
                      onChange={() => onToggleLead(lead.id)}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => onToggleExpand(lead.id)}
                      className="flex min-w-0 items-center gap-2 text-left"
                    >
                      <span className={`material-symbols-outlined text-[18px] text-on-surface-variant/60 transition-transform ${expanded ? "rotate-180" : ""}`}>expand_more</span>
                      <span className="min-w-0">
                        <span className="block font-medium text-on-surface">{name || "Unnamed lead"}</span>
                        <span className="mt-0.5 block text-xs text-on-surface-variant/65">{lead.email || "No email recorded"}</span>
                      </span>
                    </button>
                  </td>
                  <td className="px-3 py-3 text-on-surface-variant">
                    {lead.company || "—"}
                    {lead.website && <p className="mt-0.5 max-w-40 truncate text-xs text-on-surface-variant/55">{lead.website}</p>}
                  </td>
                  <td className="px-3 py-3 text-on-surface-variant">{lead.title || "—"}</td>
                  <td className="px-3 py-3 text-on-surface-variant">{lead.location || "—"}</td>
                  <td className="px-3 py-3 text-on-surface-variant">{lead.industry || "—"}</td>
                  <td className="px-3 py-3">
                    <span className="rounded-full bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary">
                      {lead.source_label}
                    </span>
                  </td>
                </tr>
                {expanded && details && (
                  <tr className="border-b border-outline-variant/10 bg-surface-lowest">
                    <td colSpan={7} className="px-6 py-5 md:px-8">
                      <p className="mb-3 text-xs text-on-surface-variant/65">
                        Source: {lead.source_label}
                        {lead.source_provenance.length > 1
                          ? ` · Also observed via ${lead.source_provenance.filter((source) => source !== lead.source_label).join(", ")}`
                          : ""}
                      </p>
                      <DiscoveryLeadDetails
                        rec={details}
                        selected={selected.has(lead.id)}
                        onToggle={() => onToggleLead(lead.id)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function leadsFoundSoFar(run: DiscoveryData | null): number {
  if (!run) return 0;
  const match = /\b(\d+) leads found/i.exec(run.progress?.stage || "");
  return match ? Number(match[1]) : run.leadCount;
}

function DiscoverySearchStatus({
  query,
  run,
  starting,
  error,
}: {
  query: string;
  run: DiscoveryData | null;
  starting: boolean;
  error: string;
}) {
  if (error) {
    return (
      <div className="rounded-xl border border-error/30 bg-error/5 px-5 py-4 text-sm text-error">
        {error}
      </div>
    );
  }

  const progress: DiscoveryProgress | undefined = starting && !run
    ? { stage: "Preparing your search", progress: 6 }
    : run?.progress;
  const count = leadsFoundSoFar(run);

  return (
    <section className="space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-sm">
        <p className="text-on-surface">
          Searching for: <span className="font-medium">{query}</span>
        </p>
        {count > 0 && <span className="text-on-surface-variant">{count} lead{count === 1 ? "" : "s"} found so far</span>}
      </div>
      <DiscoveryExecutionPanel
        progress={progress}
        plan={run?.plan}
        narrative="Interpreting your target and assessing matching leads saved in this workspace."
      />
    </section>
  );
}

function DiscoveryWorkspace({ workspaceId, scope }: { workspaceId: string; scope: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const providerSearchEnabled = useBetaFeature("lead_search");
  const query = params.get("q") || "";
  const page = Math.max(Number(params.get("page") || "1") || 1, 1);
  const providerDiscoveryId = params.get("provider_discovery") || "";
  const campaignMode = parseDiscoveryMode(params);
  const campaignContext = campaignMode.mode === "campaign_attach" ? campaignMode.context?.campaignId || "" : null;
  const filters = useMemo(
    () => Object.fromEntries(FILTERS.map(({ key }) => [key, params.get(key) || ""])),
    [params],
  );
  // The existing navigation cache keeps only IDs for this exact workspace/search.
  // URL context and server authorization remain authoritative.
  const selectionScope = discoverySelectionScope(scope, new URLSearchParams(params.toString()));
  const [draftQuery, setDraftQuery] = useState(query);
  const draftInput = useRef(draftQuery);
  draftInput.current = draftQuery;
  const [workspaceLeads, setWorkspaceLeads] = useState<WorkspaceLeadRecord[]>([]);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [loadedScope, setLoadedScope] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resultWarning, setResultWarning] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set(getNavState<string[]>(`discovery:${scope}`, selectionScope) || []));
  const [selectedScope, setSelectedScope] = useState(selectionScope);
  const [campaignBusy, setCampaignBusy] = useState(false);
  const campaignBusyRef = useRef(false);
  const [loadedRun, setProviderRun] = useState<DiscoveryData | null>(null);
  const providerRun = loadedRun?.id === providerDiscoveryId ? loadedRun : null;
  const [providerFailure, setProviderFailure] = useState({ scope: "", message: "" });
  const providerErrorScope = `${query}:${providerDiscoveryId}`;
  const providerError = providerFailure.scope === providerErrorScope ? providerFailure.message : providerRun?.status === "failed" || providerRun?.status === "cancelled" ? terminalDiscoveryMessage(providerRun) : "";
  const setProviderError = (message: string, failureScope = providerErrorScope) => setProviderFailure({ scope: failureScope, message });
  const providerErrorWriter = useRef(setProviderError);
  providerErrorWriter.current = setProviderError;
  const currentRunId = useRef(providerDiscoveryId);
  currentRunId.current = providerDiscoveryId;
  const [startingSearch, setStartingSearch] = useState(false);
  const startingSearchRef = useRef(false);
  const restoredRunRef = useRef(false);
  const [pendingQuery, setPendingQuery] = useState("");
  const pendingSearch = useRef(pendingQuery);
  pendingSearch.current = pendingQuery;
  const [expandedLeadId, setExpandedLeadId] = useState<string | null>(null);
  const mounted = useRef(true);
  const intent = useRef(0);
  const resultRequest = useRef(0);
  const searchRequest = useRef(0);
  const resultController = useRef<AbortController | null>(null);
  const selectionOwner = useRef(selectionScope);
  const observedUrl = useRef(params.toString());
  if (observedUrl.current !== params.toString()) {
    observedUrl.current = params.toString();
    intent.current++;
    resultRequest.current++;
    searchRequest.current++;
  }
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; intent.current++; resultController.current?.abort(); };
  }, []);
  const hasSearch = Boolean(query.trim());
  const hasFilters = Object.values(filters).some(Boolean);
  const runIsActive = Boolean(pendingQuery)
    || startingSearch
    || Boolean(providerDiscoveryId && !providerRun && !providerError)
    || providerRun?.status === "queued"
    || providerRun?.status === "searching";

  // Pagination preserves selection; a different search/filter/run/destination does not.
  const currentSelection = selectionOwner.current === selectionScope ? selected : new Set<string>();
  const currentResultScope = useRef("");
  currentResultScope.current = `${selectionScope}:${page}`;
  useEffect(() => {
    if (selectionOwner.current !== selectionScope) {
      selectionOwner.current = selectionScope;
      setSelected(new Set());
      setSelectedScope(selectionScope);
    }
    setExpandedLeadId(null);
    setWorkspaceLeads([]);
    setWorkspaceTotal(0);
    campaignBusyRef.current = false;
    setCampaignBusy(false);
  }, [selectionScope]);

  useEffect(() => {
    if (selectedScope === selectionScope) setNavState(`discovery:${scope}`, selectionScope, [...selected]);
  }, [selected, selectedScope, selectionScope, scope]);

  useEffect(() => {
    setDraftQuery(query);
    setPendingQuery("");
    setStartingSearch(false);
    startingSearchRef.current = false;
  }, [params.toString()]);

  const writeState = (
    next: Record<string, string>,
    nextProviderDiscoveryId = providerDiscoveryId,
    history: "push" | "replace" = "replace",
  ) => {
    intent.current++;
    resultRequest.current++;
    resultController.current?.abort();
    const url = new URLSearchParams();
    url.set("workspace_id", workspaceId);
    const creationKey = params.get("campaign_creation_key");
    if (creationKey) url.set("campaign_creation_key", creationKey);
    if (campaignContext !== null) {
      url.set("mode", "campaign_attach");
      url.set("campaign_id", campaignContext);
      for (const key of ["campaign_name", "objective", "audience", "messaging_angle"]) {
        const value = params.get(key);
        if (value) url.set(key, value);
      }
    }
    Object.entries(next).forEach(([key, value]) => {
      if (value) url.set(key, value);
    });
    if (nextProviderDiscoveryId) url.set("provider_discovery", nextProviderDiscoveryId);
    if (discoverySelectionScope(scope, url) !== selectionScope) setSelected(new Set());
    const path = `/discovery${url.size ? `?${url.toString()}` : ""}`;
    if (history === "push") router.push(path);
    else router.replace(path);
  };

  useEffect(() => {
    if (query) {
      restoredRunRef.current = true;
      try { rememberDiscoveryContext(window.sessionStorage, scope, new URLSearchParams(params.toString())); } catch { /* URL remains available. */ }
      return;
    }
    if (params.size) { restoredRunRef.current = true; return; }
    if (restoredRunRef.current) return;
    restoredRunRef.current = true;
    let active = true;
    const revision = intent.current;
    const restoreDurableRun = async () => {
      const remembered = restoredDiscoveryContext(window.sessionStorage, scope, new URLSearchParams());
      if (remembered) { if (active && revision === intent.current) router.replace(remembered); return; }
      const candidates = (await fetchDiscoveryListFresh(workspaceId) || [])
          .filter((item) => item.status === "queued" || item.status === "searching")
          .slice(0, 1)
          .map((item) => item.id);

      for (const discoveryId of candidates) {
        const run = await fetchDiscoveryFresh(discoveryId, workspaceId);
        if (!active || revision !== intent.current || draftInput.current.trim()) return;
        if (!run || (run.status !== "queued" && run.status !== "searching")) {
          continue;
        }
        writeState({ q: run.query, page: "1" }, run.id);
        return;
      }
    };

    void restoreDurableRun().catch(() => {
      if (active && revision === intent.current && !draftInput.current.trim()) setProviderError("Previous search could not be restored. Start a new search or open Search history.");
    });
    return () => { active = false; };
    // Intentionally restores once per mounted blank Discover route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString(), scope]);

  const loadWorkspaceLeads = async () => {
    if (!hasSearch) return;
    const resultScope = currentResultScope.current;
    const revision = ++resultRequest.current;
    resultController.current?.abort();
    const controller = new AbortController();
    resultController.current = controller;
    const isCurrent = () => discoveryResponseIsCurrent({ scope: resultScope, revision }, { scope: currentResultScope.current, revision: resultRequest.current }, mounted.current, controller.signal);
    setLoading(true);
    setError("");
    try {
      const result = await listWorkspaceLeads(activeSessionToken(), query, page, filters, providerDiscoveryId, controller.signal, workspaceId);
      if (!isCurrent()) return;
      setWorkspaceLeads(result.leads);
      setWorkspaceTotal(result.total);
      setResultWarning((result.warnings || []).join(" "));
      setLoadedScope(resultScope);
    } catch (loadError) {
      if (!isCurrent()) return;
      setWorkspaceLeads([]);
      setWorkspaceTotal(0);
      setResultWarning("");
      setError(loadError instanceof TimeoutError
        ? "Loading saved leads timed out. This does not mean the search failed. Retry loading the results."
        : "Could not load search results. Please try again.");
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };
  const resultLoader = useRef(loadWorkspaceLeads);
  resultLoader.current = loadWorkspaceLeads;

  useEffect(() => {
    if (!hasSearch) {
      setWorkspaceLeads([]);
      setWorkspaceTotal(0);
      setResultWarning("");
      setError("");
      setLoading(false);
      return;
    }
    void loadWorkspaceLeads();
    // URL-backed query/filter state deliberately controls this canonical read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, page, providerDiscoveryId, JSON.stringify(filters)]);

  useEffect(() => {
    if (!providerDiscoveryId) {
      setProviderRun(null);
      return;
    }
    let active = true;
    setProviderRun(null);
    setProviderError("");
    let retryTimer: number | undefined;
    const refresh = async () => {
      try {
        const next = await fetchDiscoveryFresh(providerDiscoveryId, workspaceId);
        if (!active || currentRunId.current !== providerDiscoveryId) return;
        if (startingSearchRef.current || pendingSearch.current) {
          retryTimer = window.setTimeout(() => void refresh(), 4000);
          return;
        }
        if (!next) {
          setProviderRun(null);
          providerErrorWriter.current("This saved search is unavailable or could not be refreshed.");
          return;
        }
        setProviderRun(next);
        if (!new URLSearchParams(observedUrl.current).get("q")) {
          const savedFilters = discoverySavedFilters(next.metadata);
          writeState({ ...savedFilters, ...Object.fromEntries(Object.entries(filters).filter(([key]) => params.has(key))), q: next.query, page: String(page) }, next.id);
        }
        if (next?.status === "queued" || next?.status === "searching") {
          providerErrorWriter.current("");
          retryTimer = window.setTimeout(() => void refresh(), 4000);
        } else if (next?.status === "completed") {
          providerErrorWriter.current("");
          void resultLoader.current();
        } else if (next?.status === "failed" || next?.status === "cancelled") {
          providerErrorWriter.current(terminalDiscoveryMessage(next));
          void resultLoader.current();
        }
      } catch {
        if (active && currentRunId.current === providerDiscoveryId && !startingSearchRef.current && !pendingSearch.current) providerErrorWriter.current("Discovery search could not be loaded.");
      }
    };
    void refresh();
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
    // The durable discovery id identifies the existing job/run to poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerDiscoveryId]);

  const runSearch = async (requestedQuery = draftQuery) => {
    if (campaignBusyRef.current) return;
    const nextQuery = requestedQuery.trim();
    if (!nextQuery || startingSearchRef.current) return;
    const revision = ++intent.current;
    const submission = ++searchRequest.current;
    resultRequest.current++;
    resultController.current?.abort();
    setSelected(new Set());
    startingSearchRef.current = true;
    setDraftQuery(nextQuery);
    setPendingQuery(nextQuery);
    setProviderError("");

    if (!providerSearchEnabled) {
      setProviderError("Search capabilities could not be confirmed. Reload the page and try again.");
      setPendingQuery("");
      startingSearchRef.current = false;
      return;
    }

    setStartingSearch(true);
    setProviderRun(null);
    try {
      const started = await startDiscoverySearch(nextQuery, "manual", workspaceId, filters);
      if (!mounted.current || revision !== intent.current) return;
      if (!started?.discoveryId) throw new Error("Search could not be started.");
      writeState({ ...filters, q: nextQuery, page: "1" }, started.discoveryId, "push");
    } catch (startError) {
      if (!mounted.current || revision !== intent.current) return;
      // A run failure never removes the user's canonical workspace results.
      setProviderError(startError instanceof TimeoutError
        ? "The search-start response timed out. The search may already be running; check Search history before starting another."
        : "Discovery search could not be started.", `${nextQuery}:`);
      writeState({ ...filters, q: nextQuery, page: "1" }, "", "push");
      setPendingQuery("");
    } finally {
      if (mounted.current && submission === searchRequest.current) { setStartingSearch(false); startingSearchRef.current = false; }
    }
  };

  const updateFilter = (key: string, value: string) => {
    if (campaignBusyRef.current || startingSearchRef.current) return;
    writeState({ ...filters, q: query, page: "1", [key]: value });
  };
  const clearSearch = () => {
    if (campaignBusyRef.current || startingSearchRef.current) return;
    setDraftQuery("");
    setSelected(new Set());
    setProviderError("");
    setPendingQuery("");
    setExpandedLeadId(null);
    forgetRememberedDiscovery();
    writeState({ fresh: "1" }, "", "push");
  };
  const clearFilters = () => {
    if (campaignBusyRef.current || startingSearchRef.current) return;
    writeState(query ? { q: query, page: "1" } : {}, providerDiscoveryId, "push");
  };

  const selectedOnPage = workspaceLeads.length > 0 && workspaceLeads.every((lead) => currentSelection.has(lead.id));
  const toggleVisible = () => {
    if (campaignBusyRef.current || loading || loadedScope !== currentResultScope.current) return;
    setSelected((current) => {
    const next = new Set(current);
    workspaceLeads.forEach((lead) => {
      if (selectedOnPage) next.delete(lead.id);
      else next.add(lead.id);
    });
    return next;
    });
  };
  const toggleLead = (leadId: string) => {
    if (campaignBusyRef.current || loading || loadedScope !== currentResultScope.current || !workspaceLeads.some((lead) => lead.id === leadId)) return;
    setSelected((current) => {
    const next = new Set(current);
    if (next.has(leadId)) next.delete(leadId);
    else next.add(leadId);
    return next;
    });
  };
  const toggleExpandedLead = (leadId: string) => {
    setExpandedLeadId((current) => current === leadId ? null : leadId);
  };
  const detailsByLeadId = useMemo(() => {
    const details = new Map<string, DiscoveryRecommendation>();
    providerRun?.recommendations.forEach((recommendation) => {
      details.set(recommendation.id, recommendation);
    });
    workspaceLeads.forEach((lead, index) => {
      if (!details.has(lead.id)) {
        details.set(
          lead.id,
          workspaceLeadToRecommendation({
            ...lead,
            company_name: lead.company,
            buying_signal: lead.source_kind === "provider"
              ? "Provider result"
              : "No additional Discovery signal recorded",
            buying_signal_detail: lead.source_kind === "provider"
              ? "This lead was surfaced by the completed provider search."
              : "No provider research signal is available for this saved lead.",
          } as Record<string, unknown>, index),
        );
      }
    });
    return details;
  }, [providerRun?.recommendations, workspaceLeads]);

  const searchForm = (
    <form
      className="flex flex-col gap-3 sm:flex-row"
      onSubmit={(event) => {
        event.preventDefault();
        void runSearch();
      }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-3 rounded-xl border border-outline-variant/25 bg-surface-lowest px-4 py-3 shadow-sm focus-within:border-primary/50">
        <span className="text-lg text-primary">✦</span>
        <input
          aria-label="Describe the leads you're looking for"
          value={draftQuery}
          onChange={(event) => setDraftQuery(event.target.value)}
          placeholder="Describe the leads you're looking for..."
          className="min-w-0 flex-1 bg-transparent text-base text-on-surface outline-none placeholder:text-on-surface-variant/45"
        />
        {hasSearch && (
          <button
            type="button"
            aria-label="Clear Discover search"
            onClick={clearSearch}
            className="text-on-surface-variant/60 transition-colors hover:text-on-surface"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        )}
      </div>
      <button
        type="submit"
        disabled={!draftQuery.trim() || startingSearch || campaignBusy}
        className="rounded-lg bg-primary px-5 py-3 text-sm font-medium text-on-primary transition-opacity disabled:opacity-40"
      >
        {startingSearch ? "Starting…" : "Search"}
      </button>
      {(hasSearch || providerDiscoveryId) && <button type="button" disabled={startingSearch || campaignBusy} onClick={clearSearch} className="text-sm text-on-surface-variant">New search</button>}
    </form>
  );

  return (
    <main className="flex h-full min-h-0 bg-surface">
      <FilterRail workspaceId={workspaceId} filters={filters} hasFilters={hasFilters} onChange={updateFilter} onClear={clearFilters} disabled={campaignBusy || startingSearch} />
      <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 px-5 md:px-6">
          <DiscoveryCampaignActions
            key={selectionScope}
            workspaceId={workspaceId}
            leadIds={[...currentSelection]}
            campaignContext={campaignContext}
            onComplete={(attachedIds) => { if (selectionOwner.current === selectionScope) setSelected((current) => new Set([...current].filter((id) => !attachedIds.includes(id)))); }}
            onBusy={(busy) => { if (selectionOwner.current === selectionScope) { campaignBusyRef.current = busy; setCampaignBusy(busy); } }}
          />
        </div>
        {!hasSearch && !runIsActive && !providerError ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6">
            <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Discover</p>
              </div>
              <h1 className="mt-3 font-serif text-4xl tracking-tight text-on-surface md:text-5xl">Who are you looking for?</h1>
              <p className="mt-3 text-sm text-on-surface-variant">Search leads saved in this workspace. To add your own data, <Link className="text-primary underline" href={`/contacts?workspace_id=${encodeURIComponent(workspaceId)}`}>import a CSV</Link>.</p>
              <div className="mt-8">{searchForm}</div>
              <div className="mt-9">
                <p className="mb-3 text-sm font-medium text-on-surface-variant">Suggested for you</p>
                <div className="space-y-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => void runSearch(suggestion)}
                      className="flex w-full items-center justify-between rounded-lg border border-outline-variant/20 bg-surface-lowest px-4 py-3 text-left text-sm text-on-surface-variant transition-colors hover:border-primary/40 hover:text-on-surface"
                    >
                      <span><span className="mr-3 text-primary">✦</span>{suggestion}</span>
                      <span className="material-symbols-outlined text-[18px] text-primary">arrow_forward</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="shrink-0 border-b border-outline-variant/15 bg-surface px-5 py-4 md:px-6">
              {searchForm}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6">
              <div className="space-y-5">
                {runIsActive && <DiscoverySearchStatus query={pendingQuery || (startingSearch ? draftQuery : query)} run={providerRun} starting={startingSearch} error={providerError} />}
                {!runIsActive && providerError && <DiscoverySearchStatus query={query} run={providerRun} starting={false} error={providerError} />}
                {!runIsActive && providerRun?.status === "completed" && (
                  <DiscoveryResearchBriefing view={providerRun} resultCount={workspaceTotal} />
                )}

                {!runIsActive && loadedScope === currentResultScope.current && resultWarning && <p role="alert" className="text-sm text-on-surface-variant">{resultWarning}</p>}
                {!runIsActive && hasSearch && (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-sm text-on-surface-variant">
                        <span className="font-semibold text-on-surface">{workspaceTotal}</span> result{workspaceTotal === 1 ? "" : "s"}
                      </p>
                      {currentSelection.size > 0 && (
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-primary">{currentSelection.size} selected</span>
                          <button type="button" disabled={campaignBusy} onClick={() => setSelected(new Set())} className="text-sm text-on-surface-variant hover:text-primary">
                            Clear selection
                          </button>
                        </div>
                      )}
                    </div>
                    {error ? (
                      <div className="rounded-xl border border-error/30 bg-error/5 p-6 text-center">
                        <p className="font-medium text-error">{error}</p>
                        <button type="button" onClick={() => void loadWorkspaceLeads()} className="mt-3 text-sm text-primary hover:underline">Try again</button>
                      </div>
                    ) : loading || loadedScope !== currentResultScope.current ? (
                      <div className="flex min-h-64 items-center justify-center rounded-xl border border-outline-variant/20 bg-surface-lowest text-sm text-on-surface-variant">
                        <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                        Loading matching leads…
                      </div>
                    ) : workspaceLeads.length === 0 ? (
                      <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant/30 bg-surface-lowest p-8 text-center">
                        <p className="font-medium text-on-surface">{resultWarning ? "Search results are temporarily incomplete." : "No leads match this search."}</p>
                        <p className="mt-1 text-sm text-on-surface-variant">Try another keyword or filter. If this workspace has no leads yet, <Link className="text-primary underline" href={`/contacts?workspace_id=${encodeURIComponent(workspaceId)}`}>import a CSV</Link>.</p>
                      </div>
                    ) : (
                      <>
                        <LeadResultsTable
                          leads={workspaceLeads}
                          selected={currentSelection}
                          selectedOnPage={selectedOnPage}
                          expandedLeadId={expandedLeadId}
                          detailsByLeadId={detailsByLeadId}
                          onToggleVisible={toggleVisible}
                          onToggleLead={toggleLead}
                          onToggleExpand={toggleExpandedLead}
                          disabled={campaignBusy}
                        />
                        {workspaceTotal > PAGE_SIZE && (
                          <nav className="flex items-center justify-between" aria-label="Lead results pagination">
                            <button
                              type="button"
                              disabled={page === 1}
                              onClick={() => writeState({ ...filters, q: query, page: String(page - 1) })}
                              className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40"
                            >
                              Previous
                            </button>
                            <span className="text-sm text-on-surface-variant">Page {page} of {Math.ceil(workspaceTotal / PAGE_SIZE)}</span>
                            <button
                              type="button"
                              disabled={page * PAGE_SIZE >= workspaceTotal}
                              onClick={() => writeState({ ...filters, q: query, page: String(page + 1) })}
                              className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40"
                            >
                              Next
                            </button>
                          </nav>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </section>
    </main>
  );
}

export default function DiscoveryPage() {
  const params = useSearchParams();
  const context = useIntelligenceWorkspace(params.get("workspace_id") || "", params.size === 0);
  if (!context.workspace) return <div role={context.error ? "alert" : "status"} className="p-6">{context.error || "Loading your workspace…"}</div>;
  return <DiscoveryWorkspace key={context.scope} workspaceId={context.workspace} scope={context.scope} />;
}
