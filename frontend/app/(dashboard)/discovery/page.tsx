"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import DiscoveryHistory from "../../../components/dashboard/DiscoveryHistory";
import {
  DiscoveryExecutionPanel,
  DiscoveryLeadDetails,
  DiscoveryResearchBriefing,
} from "../../../components/dashboard/DiscoveryDetailWorkspace";
import { useBetaFeature } from "../../../contexts/BetaFeaturesContext";
import { listWorkspaceLeads, type WorkspaceLeadRecord } from "../../../lib/api";
import { parseDiscoveryMode } from "../../../lib/discovery-mode";
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

// This is a navigation hint, not a second discovery state store. The durable
// discovery row remains authoritative and is always re-authorized by the API
// before the page restores it. Keeping only its id lets a mounted page reconnect
// after route navigation without coupling a server-side job to React's lifetime.
const ACTIVE_DISCOVERY_KEY = "loqi_active_discovery";

function rememberedDiscoveryId(): string {
  try {
    return window.sessionStorage.getItem(ACTIVE_DISCOVERY_KEY) || "";
  } catch {
    return "";
  }
}

function rememberDiscovery(id: string): void {
  try {
    if (id) window.sessionStorage.setItem(ACTIVE_DISCOVERY_KEY, id);
  } catch {
    // URL state and the workspace-scoped API remain sufficient when storage
    // is unavailable (for example, a privacy-restricted browser session).
  }
}

function forgetRememberedDiscovery(): void {
  try {
    window.sessionStorage.removeItem(ACTIVE_DISCOVERY_KEY);
  } catch {
    // See rememberDiscovery.
  }
}

function terminalDiscoveryMessage(run: DiscoveryData): string {
  if (run.status === "cancelled") {
    return "This search was stopped before it completed. Your saved leads are still available.";
  }
  switch (run.failure?.kind) {
    case "timeout":
      return "The provider did not respond in time after its retry budget. Your saved leads are still available.";
    case "permanent":
      return "The configured provider could not accept this search. Check its connection and try again.";
    case "persistence":
      return "Matching leads were found, but their results could not be saved. Please try the search again.";
    default:
      return "This search failed before it completed. Your saved leads are still available.";
  }
}

function FilterRail({
  filters,
  hasFilters,
  onChange,
  onClear,
}: {
  filters: Record<string, string>;
  hasFilters: boolean;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-y-auto border-r border-outline-variant/15 bg-surface-lowest px-4 py-5 lg:w-[304px] lg:shrink-0">
      <div className="mb-5 flex items-center justify-between px-1">
        <h1 className="text-sm font-semibold text-on-surface">Filters</h1>
        <button
          type="button"
          disabled={!hasFilters}
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
        href="/discovery/history"
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
}: {
  leads: WorkspaceLeadRecord[];
  selected: Set<string>;
  selectedOnPage: boolean;
  expandedLeadId: string | null;
  detailsByLeadId: Map<string, DiscoveryRecommendation>;
  onToggleVisible: () => void;
  onToggleLead: (leadId: string) => void;
  onToggleExpand: (leadId: string) => void;
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
        narrative="Searching available sources and matching results to your target."
      />
    </section>
  );
}

function DiscoveryWorkspace() {
  const router = useRouter();
  const params = useSearchParams();
  const providerSearchEnabled = useBetaFeature("lead_search");
  const query = params.get("q") || "";
  const page = Math.max(Number(params.get("page") || "1") || 1, 1);
  const providerDiscoveryId = params.get("provider_discovery") || "";
  const filters = useMemo(
    () => Object.fromEntries(FILTERS.map(({ key }) => [key, params.get(key) || ""])),
    [params],
  );
  const [draftQuery, setDraftQuery] = useState(query);
  const [workspaceLeads, setWorkspaceLeads] = useState<WorkspaceLeadRecord[]>([]);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [providerRun, setProviderRun] = useState<DiscoveryData | null>(null);
  const [providerError, setProviderError] = useState("");
  const [startingSearch, setStartingSearch] = useState(false);
  const startingSearchRef = useRef(false);
  const restoredRunRef = useRef(false);
  const [pendingQuery, setPendingQuery] = useState("");
  const [expandedLeadId, setExpandedLeadId] = useState<string | null>(null);
  const hasSearch = Boolean(query.trim());
  const hasFilters = Object.values(filters).some(Boolean);
  const runIsActive = Boolean(pendingQuery)
    || startingSearch
    || Boolean(providerDiscoveryId && !providerRun && !providerError)
    || providerRun?.status === "queued"
    || providerRun?.status === "searching";

  useEffect(() => {
    setDraftQuery(query);
    if (pendingQuery && query === pendingQuery) setPendingQuery("");
  }, [providerDiscoveryId, query]);

  const writeState = (
    next: Record<string, string>,
    nextProviderDiscoveryId = providerDiscoveryId,
    history: "push" | "replace" = "replace",
  ) => {
    const url = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => {
      if (value) url.set(key, value);
    });
    if (nextProviderDiscoveryId) url.set("provider_discovery", nextProviderDiscoveryId);
    const path = `/discovery${url.size ? `?${url.toString()}` : ""}`;
    if (history === "push") router.push(path);
    else router.replace(path);
  };

  useEffect(() => {
    // URL state remains the shareable source for a particular run. When a
    // user leaves Discover through normal navigation, this session-scoped
    // pointer reconnects the page to the already-durable run on return. It
    // never starts, cancels, or mutates the server-side job.
    if (providerDiscoveryId || query || restoredRunRef.current) return;
    restoredRunRef.current = true;
    let active = true;

    const restoreDurableRun = async () => {
      const remembered = rememberedDiscoveryId();
      const candidates = remembered
        ? [remembered]
        : (await fetchDiscoveryListFresh() || [])
          .filter((item) => item.status === "queued" || item.status === "searching")
          .slice(0, 1)
          .map((item) => item.id);

      for (const discoveryId of candidates) {
        const run = await fetchDiscoveryFresh(discoveryId);
        if (!active) return;
        if (!run || (run.status !== "queued" && run.status !== "searching")) {
          if (discoveryId === remembered) forgetRememberedDiscovery();
          continue;
        }
        rememberDiscovery(run.id);
        writeState({ q: run.query, page: "1" }, run.id);
        return;
      }
    };

    void restoreDurableRun().catch(() => {
      // A recovery hint must not make a normal first visit fail. The
      // workspace-scoped run will be retried the next time Discover mounts.
    });
    return () => { active = false; };
    // Intentionally restores once per mounted blank Discover route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerDiscoveryId, query]);

  const loadWorkspaceLeads = async () => {
    if (!hasSearch) return;
    setLoading(true);
    setError("");
    try {
      const result = await listWorkspaceLeads(activeSessionToken(), query, page, filters, providerDiscoveryId);
      setWorkspaceLeads(result.leads);
      setWorkspaceTotal(result.total);
    } catch {
      setWorkspaceLeads([]);
      setWorkspaceTotal(0);
      setError("Could not load search results. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!hasSearch) {
      setWorkspaceLeads([]);
      setWorkspaceTotal(0);
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
    let retryTimer: number | undefined;
    const refresh = async () => {
      try {
        const next = await fetchDiscoveryFresh(providerDiscoveryId);
        if (!active) return;
        if (!next) {
          setProviderRun(null);
          setProviderError("This saved search is unavailable or could not be refreshed.");
          return;
        }
        setProviderRun(next);
        if (next?.status === "queued" || next?.status === "searching") {
          rememberDiscovery(next.id);
          setProviderError("");
          retryTimer = window.setTimeout(() => void refresh(), 4000);
        } else if (next?.status === "completed") {
          forgetRememberedDiscovery();
          setProviderError("");
          void loadWorkspaceLeads();
        } else if (next?.status === "failed" || next?.status === "cancelled") {
          forgetRememberedDiscovery();
          setProviderError(terminalDiscoveryMessage(next));
        }
      } catch {
        if (active) setProviderError("Discovery search could not be loaded.");
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
    const nextQuery = requestedQuery.trim();
    if (!nextQuery || startingSearchRef.current) return;
    startingSearchRef.current = true;
    setDraftQuery(nextQuery);
    setPendingQuery(nextQuery);
    setProviderError("");

    if (!providerSearchEnabled) {
      writeState({ ...filters, q: nextQuery, page: "1" }, "", "push");
      setPendingQuery("");
      startingSearchRef.current = false;
      return;
    }

    setStartingSearch(true);
    setProviderRun(null);
    try {
      const started = await startDiscoverySearch(nextQuery, "manual");
      if (!started?.discoveryId) throw new Error("Search could not be started.");
      rememberDiscovery(started.discoveryId);
      writeState({ ...filters, q: nextQuery, page: "1" }, started.discoveryId, "push");
    } catch {
      // A run failure never removes the user's canonical workspace results.
      setProviderError("Discovery search could not be started.");
      writeState({ ...filters, q: nextQuery, page: "1" }, "", "push");
      setPendingQuery("");
    } finally {
      setStartingSearch(false);
      startingSearchRef.current = false;
    }
  };

  const updateFilter = (key: string, value: string) => {
    writeState({ ...filters, q: query, page: "1", [key]: value });
  };
  const clearSearch = () => {
    setDraftQuery("");
    setSelected(new Set());
    setProviderError("");
    setPendingQuery("");
    setExpandedLeadId(null);
    forgetRememberedDiscovery();
    writeState({}, "", "push");
  };
  const clearFilters = () => {
    writeState(query ? { q: query, page: "1" } : {}, providerDiscoveryId, "push");
  };

  const selectedOnPage = workspaceLeads.length > 0 && workspaceLeads.every((lead) => selected.has(lead.id));
  const toggleVisible = () => setSelected((current) => {
    const next = new Set(current);
    workspaceLeads.forEach((lead) => {
      if (selectedOnPage) next.delete(lead.id);
      else next.add(lead.id);
    });
    return next;
  });
  const toggleLead = (leadId: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(leadId)) next.delete(leadId);
    else next.add(leadId);
    return next;
  });
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
        disabled={!draftQuery.trim() || startingSearch}
        className="rounded-lg bg-primary px-5 py-3 text-sm font-medium text-on-primary transition-opacity disabled:opacity-40"
      >
        {startingSearch ? "Starting…" : "Search"}
      </button>
    </form>
  );

  return (
    <main className="flex h-full min-h-0 bg-surface">
      <FilterRail filters={filters} hasFilters={hasFilters} onChange={updateFilter} onClear={clearFilters} />
      <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!hasSearch && !runIsActive ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6">
            <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Discover</p>
              </div>
              <h1 className="mt-3 font-serif text-4xl tracking-tight text-on-surface md:text-5xl">Who are you looking for?</h1>
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

                {!runIsActive && (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-sm text-on-surface-variant">
                        <span className="font-semibold text-on-surface">{workspaceTotal}</span> result{workspaceTotal === 1 ? "" : "s"}
                      </p>
                      {selected.size > 0 && (
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-primary">{selected.size} selected</span>
                          <button
                            type="button"
                            className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary"
                            onClick={() => router.push(`/lead-intelligence?lead_ids=${encodeURIComponent([...selected].join(","))}`)}
                          >
                            Analyze with Loqi
                          </button>
                          <button type="button" onClick={() => setSelected(new Set())} className="text-sm text-on-surface-variant hover:text-primary">
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
                    ) : loading ? (
                      <div className="flex min-h-64 items-center justify-center rounded-xl border border-outline-variant/20 bg-surface-lowest text-sm text-on-surface-variant">
                        <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                        Loading matching leads…
                      </div>
                    ) : workspaceLeads.length === 0 ? (
                      <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant/30 bg-surface-lowest p-8 text-center">
                        <p className="font-medium text-on-surface">No leads match this search.</p>
                        <p className="mt-1 text-sm text-on-surface-variant">Try a broader query or adjust the filters.</p>
                      </div>
                    ) : (
                      <>
                        <LeadResultsTable
                          leads={workspaceLeads}
                          selected={selected}
                          selectedOnPage={selectedOnPage}
                          expandedLeadId={expandedLeadId}
                          detailsByLeadId={detailsByLeadId}
                          onToggleVisible={toggleVisible}
                          onToggleLead={toggleLead}
                          onToggleExpand={toggleExpandedLead}
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
  if (parseDiscoveryMode(params).mode === "campaign_attach") return <DiscoveryHistory />;
  return <DiscoveryWorkspace />;
}
