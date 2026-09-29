"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import DiscoveryHistory from "../../../components/dashboard/DiscoveryHistory";
import { useBetaFeature } from "../../../contexts/BetaFeaturesContext";
import { listWorkspaceLeads, type WorkspaceLeadRecord } from "../../../lib/api";
import { parseDiscoveryMode } from "../../../lib/discovery-mode";
import { fetchDiscoveryFresh, startDiscoverySearch } from "../../../lib/repositories";
import type { DiscoveryData } from "../../../lib/domain";

const PAGE_SIZE = 50;
const FILTERS = [
  { key: "location", label: "Headquarters location", placeholder: "e.g. United States", supported: true },
  { key: "industry", label: "Industry", placeholder: "e.g. SaaS", supported: true },
  { key: "keywords", label: "Keywords", supported: false },
  { key: "company_size", label: "Company size", supported: false },
  { key: "company", label: "Company name", placeholder: "e.g. Acme", supported: true },
  { key: "title", label: "Job title", placeholder: "e.g. COO", supported: true },
  { key: "company_type", label: "Company type", supported: false },
  { key: "job_openings", label: "Job openings", supported: false },
  { key: "saved_companies", label: "Saved companies", supported: false },
  { key: "year_founded", label: "Year founded", supported: false },
  { key: "technologies", label: "Technologies", supported: false },
  { key: "funding", label: "Funding", supported: false },
] as const;

const SUGGESTIONS = [
  "Find potential customers for Loqi",
  "Find e-commerce brands and retailers needing loyalty programs",
];

function activeSessionToken(): string {
  return window.localStorage.getItem("loqi_active_session_token") || "";
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
    <aside className="flex min-h-[calc(100vh-9rem)] flex-col border-r border-outline-variant/15 bg-surface-lowest px-4 py-6 lg:w-[304px] lg:shrink-0">
      <div className="mb-5 flex items-center justify-between px-1">
        <h1 className="text-sm font-semibold text-on-surface">Filters</h1>
        <button type="button" disabled={!hasFilters} onClick={onClear} className="text-xs font-medium text-primary disabled:text-on-surface-variant/35">Clear all</button>
      </div>
      <div className="border-y border-outline-variant/15">
        {FILTERS.map((filter) => {
          const { key, label, supported } = filter;
          const placeholder = "placeholder" in filter ? filter.placeholder : "";
          const open = expanded === key;
          return (
            <div key={key} className="border-b border-outline-variant/15 last:border-b-0">
              <button
                type="button"
                disabled={!supported}
                aria-expanded={supported ? open : undefined}
                onClick={() => setExpanded(open ? null : key)}
                className="flex w-full items-center justify-between gap-3 px-1 py-3 text-left text-sm text-on-surface transition-colors hover:text-primary disabled:cursor-not-allowed disabled:text-on-surface-variant/40"
              >
                <span>{label}</span>
                <span className="material-symbols-outlined text-[18px]">{supported ? (open ? "expand_less" : "expand_more") : "lock"}</span>
              </button>
              {supported && open && (
                <div className="pb-3">
                  <input aria-label={`Filter by ${label}`} value={filters[key] || ""} placeholder={placeholder} onChange={(event) => onChange(key, event.target.value)} className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40 focus:border-primary/50" />
                </div>
              )}
            </div>
          );
        })}
      </div>
      <button type="button" disabled title="Saved searches are not available in this Beta yet" className="mt-auto flex items-center justify-between border-t border-outline-variant/15 px-1 pt-5 text-left text-sm text-on-surface-variant/45">
        <span>Saved searches</span><span className="material-symbols-outlined text-[18px]">bookmark</span>
      </button>
    </aside>
  );
}

function LeadResultsTable({
  leads, selected, selectedOnPage, onToggleVisible, onToggleLead,
}: {
  leads: WorkspaceLeadRecord[];
  selected: Set<string>;
  selectedOnPage: boolean;
  onToggleVisible: () => void;
  onToggleLead: (leadId: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-outline-variant/20 bg-surface-lowest">
      <table className="w-full min-w-[900px] text-left text-sm">
        <thead className="border-b border-outline-variant/20 bg-surface-container-low text-xs uppercase tracking-wider text-on-surface-variant/65">
          <tr>
            <th className="w-12 px-4 py-3"><input aria-label="Select all visible leads" type="checkbox" checked={selectedOnPage} onChange={onToggleVisible} /></th>
            <th className="px-3 py-3 font-medium">Person</th><th className="px-3 py-3 font-medium">Company</th><th className="px-3 py-3 font-medium">Title</th><th className="px-3 py-3 font-medium">Location</th><th className="px-3 py-3 font-medium">Industry</th><th className="px-3 py-3 font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const name = `${lead.first_name} ${lead.last_name}`.trim();
            return (
              <tr key={lead.id} className="border-b border-outline-variant/10 transition-colors last:border-0 hover:bg-surface-container-low/55">
                <td className="px-4 py-3"><input aria-label={`Select ${name || lead.email || "lead"}`} type="checkbox" checked={selected.has(lead.id)} onChange={() => onToggleLead(lead.id)} /></td>
                <td className="px-3 py-3"><p className="font-medium text-on-surface">{name || "Unnamed lead"}</p><p className="mt-0.5 text-xs text-on-surface-variant/65">{lead.email || "No email recorded"}</p></td>
                <td className="px-3 py-3 text-on-surface-variant">{lead.company || "—"}{lead.website && <p className="mt-0.5 max-w-40 truncate text-xs text-on-surface-variant/55">{lead.website}</p>}</td>
                <td className="px-3 py-3 text-on-surface-variant">{lead.title || "—"}</td><td className="px-3 py-3 text-on-surface-variant">{lead.location || "—"}</td><td className="px-3 py-3 text-on-surface-variant">{lead.industry || "—"}</td>
                <td className="px-3 py-3"><span className="rounded-full bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary">{lead.source_label}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ProviderStatus({ run, error }: { run: DiscoveryData | null; error: string }) {
  if (error) return <p className="text-sm text-error">Provider search could not be loaded. Your current results are still available.</p>;
  if (!run) return null;
  if (run.status === "queued" || run.status === "searching") return <p className="flex items-center gap-2 text-sm text-on-surface-variant"><span className="material-symbols-outlined animate-spin text-[17px] text-primary">progress_activity</span>Searching all sources…</p>;
  if (run.status === "failed" || run.status === "cancelled") return <p className="text-sm text-error">The provider search did not complete.</p>;
  return <p className="text-sm text-on-surface-variant">Provider matches were added to these results.</p>;
}

function DiscoveryWorkspace() {
  const router = useRouter();
  const params = useSearchParams();
  const providerSearchEnabled = useBetaFeature("lead_search");
  const query = params.get("q") || "";
  const page = Math.max(Number(params.get("page") || "1") || 1, 1);
  const providerDiscoveryId = params.get("provider_discovery") || "";
  const filters = useMemo(() => Object.fromEntries(FILTERS.filter((filter) => filter.supported).map(({ key }) => [key, params.get(key) || ""])), [params]);
  const [draftQuery, setDraftQuery] = useState(query);
  const [workspaceLeads, setWorkspaceLeads] = useState<WorkspaceLeadRecord[]>([]);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [providerRun, setProviderRun] = useState<DiscoveryData | null>(null);
  const [providerError, setProviderError] = useState("");
  const [startingProviderSearch, setStartingProviderSearch] = useState(false);
  const hasSearch = Boolean(query.trim());
  const hasFilters = Object.values(filters).some(Boolean);

  useEffect(() => setDraftQuery(query), [query]);

  const writeState = (next: Record<string, string>, nextProviderDiscoveryId = providerDiscoveryId, history: "push" | "replace" = "replace") => {
    const url = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => { if (value) url.set(key, value); });
    if (nextProviderDiscoveryId) url.set("provider_discovery", nextProviderDiscoveryId);
    const path = `/discovery${url.size ? `?${url.toString()}` : ""}`;
    if (history === "push") router.push(path); else router.replace(path);
  };

  const loadWorkspaceLeads = async () => {
    if (!hasSearch) return;
    setLoading(true); setError("");
    try {
      const result = await listWorkspaceLeads(activeSessionToken(), query, page, filters, providerDiscoveryId);
      setWorkspaceLeads(result.leads); setWorkspaceTotal(result.total);
    } catch {
      setWorkspaceLeads([]); setWorkspaceTotal(0); setError("Could not load search results. Please try again.");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (!hasSearch) { setWorkspaceLeads([]); setWorkspaceTotal(0); setError(""); setLoading(false); return; }
    void loadWorkspaceLeads();
    // Search/filter state is URL-backed; no request is made while the user is merely typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, page, providerDiscoveryId, JSON.stringify(filters)]);

  useEffect(() => {
    if (!providerDiscoveryId) { setProviderRun(null); setProviderError(""); return; }
    let active = true;
    let retryTimer: number | undefined;
    const refresh = async () => {
      try {
        const next = await fetchDiscoveryFresh(providerDiscoveryId);
        if (!active) return;
        setProviderRun(next); setProviderError("");
        if (next?.status === "queued" || next?.status === "searching") retryTimer = window.setTimeout(() => void refresh(), 4000);
        else if (next?.status === "completed") void loadWorkspaceLeads();
      } catch { if (active) setProviderError("Provider search could not be loaded."); }
    };
    void refresh();
    return () => { active = false; if (retryTimer) window.clearTimeout(retryTimer); };
    // The durable run ID is the polling identity. Query/filter changes replace the URL run ID.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerDiscoveryId]);

  const submitWorkspaceSearch = (requestedQuery = draftQuery) => {
    const nextQuery = requestedQuery.trim();
    if (!nextQuery) return;
    setDraftQuery(nextQuery);
    writeState({ ...filters, q: nextQuery, page: "1" }, "", "push");
  };
  const updateFilter = (key: string, value: string) => writeState({ ...filters, q: query, page: "1", [key]: value });
  const clearSearch = () => { setDraftQuery(""); setSelected(new Set()); writeState({}, "", "push"); };
  const startProviderSearch = async () => {
    if (!query || startingProviderSearch || !providerSearchEnabled) return;
    setStartingProviderSearch(true); setProviderError("");
    try {
      const started = await startDiscoverySearch(query, "manual");
      if (!started?.discoveryId) throw new Error("Provider search could not be started.");
      writeState({ ...filters, q: query, page: "1" }, started.discoveryId, "push");
    } catch (caught) { setProviderError(caught instanceof Error ? caught.message : "Provider search could not be started."); }
    finally { setStartingProviderSearch(false); }
  };

  const selectedOnPage = workspaceLeads.length > 0 && workspaceLeads.every((lead) => selected.has(lead.id));
  const toggleVisible = () => setSelected((current) => {
    const next = new Set(current);
    workspaceLeads.forEach((lead) => selectedOnPage ? next.delete(lead.id) : next.add(lead.id));
    return next;
  });
  const toggleLead = (leadId: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(leadId)) next.delete(leadId); else next.add(leadId);
    return next;
  });

  return (
    <main className="flex min-h-[calc(100vh-4rem)] bg-surface">
      <FilterRail filters={filters} hasFilters={hasFilters} onChange={updateFilter} onClear={clearSearch} />
      <section className="min-w-0 flex-1 px-5 py-6 md:px-10">
        {!hasSearch ? (
          <div className="mx-auto flex min-h-[calc(100vh-10rem)] max-w-3xl flex-col justify-center">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-primary">Discover</p>
            <h1 className="font-serif text-4xl tracking-tight text-on-surface md:text-5xl">What companies are you targeting?</h1>
            <form className="mt-8" onSubmit={(event) => { event.preventDefault(); submitWorkspaceSearch(); }}>
              <div className="flex items-center gap-3 rounded-xl border border-outline-variant/25 bg-surface-lowest px-4 py-3 shadow-sm focus-within:border-primary/50">
                <span className="text-lg text-primary">✦</span>
                <input aria-label="Describe target companies" value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder="Describe the companies you want to target..." className="min-w-0 flex-1 bg-transparent text-base text-on-surface outline-none placeholder:text-on-surface-variant/45" />
                <button aria-label="Search workspace leads" type="submit" disabled={!draftQuery.trim()} className="rounded-lg bg-primary p-2 text-on-primary disabled:opacity-40"><span className="material-symbols-outlined">arrow_forward</span></button>
              </div>
            </form>
            <div className="mt-9"><p className="mb-3 text-sm font-medium text-on-surface-variant">Suggested for you</p><div className="space-y-2">
              {SUGGESTIONS.map((suggestion) => <button key={suggestion} type="button" onClick={() => submitWorkspaceSearch(suggestion)} className="flex w-full items-center justify-between rounded-lg border border-outline-variant/20 bg-surface-lowest px-4 py-3 text-left text-sm text-on-surface-variant transition-colors hover:border-primary/40 hover:text-on-surface"><span><span className="mr-3 text-primary">✦</span>{suggestion}</span><span className="material-symbols-outlined text-[18px] text-primary">arrow_forward</span></button>)}
            </div></div>
          </div>
        ) : (
          <div className="mx-auto max-w-[1280px] space-y-5">
            <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => { event.preventDefault(); submitWorkspaceSearch(); }}>
              <div className="flex min-w-0 flex-1 items-center gap-3 rounded-xl border border-outline-variant/25 bg-surface-lowest px-4 py-3 focus-within:border-primary/50"><span className="text-lg text-primary">✦</span><input aria-label="Search Discovery" value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} className="min-w-0 flex-1 bg-transparent text-base text-on-surface outline-none" /><button type="button" aria-label="Clear Discovery search" onClick={clearSearch} className="text-on-surface-variant/60 hover:text-on-surface"><span className="material-symbols-outlined">close</span></button></div>
              <button type="submit" disabled={!draftQuery.trim()} className="rounded-lg border border-outline-variant/25 bg-surface-lowest px-4 py-3 text-sm font-medium text-on-surface disabled:opacity-40">Search</button>
              {providerSearchEnabled && <button type="button" disabled={startingProviderSearch} onClick={() => void startProviderSearch()} className="rounded-lg bg-primary px-4 py-3 text-sm font-medium text-on-primary disabled:opacity-45">{startingProviderSearch ? "Starting…" : "Search all sources"}</button>}
            </form>
            <ProviderStatus run={providerRun} error={providerError} />
            <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-on-surface-variant"><span className="font-semibold text-on-surface">{workspaceTotal}</span> result{workspaceTotal === 1 ? "" : "s"}</p>{selected.size > 0 && <div className="flex items-center gap-3"><span className="text-sm font-medium text-primary">{selected.size} selected</span><button type="button" className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary" onClick={() => router.push(`/lead-intelligence?lead_ids=${encodeURIComponent([...selected].join(","))}`)}>Analyze with Loqi</button><button type="button" onClick={() => setSelected(new Set())} className="text-sm text-on-surface-variant hover:text-primary">Clear selection</button></div>}</div>
            {error ? <div className="rounded-xl border border-error/30 bg-error/5 p-6 text-center"><p className="font-medium text-error">{error}</p><button type="button" onClick={() => void loadWorkspaceLeads()} className="mt-3 text-sm text-primary hover:underline">Try again</button></div>
              : loading ? <div className="flex min-h-64 items-center justify-center rounded-xl border border-outline-variant/20 bg-surface-lowest text-sm text-on-surface-variant"><span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />Searching leads…</div>
                : workspaceLeads.length === 0 ? <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant/30 bg-surface-lowest p-8 text-center"><p className="font-medium text-on-surface">No leads match this search.</p><p className="mt-1 text-sm text-on-surface-variant">Try a broader query, adjust the filters, or search all sources.</p></div>
                  : <><LeadResultsTable leads={workspaceLeads} selected={selected} selectedOnPage={selectedOnPage} onToggleVisible={toggleVisible} onToggleLead={toggleLead} />{workspaceTotal > PAGE_SIZE && <nav className="flex items-center justify-between" aria-label="Lead results pagination"><button type="button" disabled={page === 1} onClick={() => writeState({ ...filters, q: query, page: String(page - 1) })} className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40">Previous</button><span className="text-sm text-on-surface-variant">Page {page} of {Math.ceil(workspaceTotal / PAGE_SIZE)}</span><button type="button" disabled={page * PAGE_SIZE >= workspaceTotal} onClick={() => writeState({ ...filters, q: query, page: String(page + 1) })} className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40">Next</button></nav>}</>}
          </div>
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
