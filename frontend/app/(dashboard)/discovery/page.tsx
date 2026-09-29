"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import DiscoveryHistory from "../../../components/dashboard/DiscoveryHistory";
import { useBetaFeature } from "../../../contexts/BetaFeaturesContext";
import { listWorkspaceLeads, type WorkspaceLeadRecord } from "../../../lib/api";
import { parseDiscoveryMode } from "../../../lib/discovery-mode";
import {
  fetchDiscoveryFresh,
  startDiscoverySearch,
} from "../../../lib/repositories";
import type { DiscoveryData } from "../../../lib/domain";

const PAGE_SIZE = 50;
const FILTERS = [
  { key: "location", label: "Location", placeholder: "e.g. United States" },
  { key: "industry", label: "Industry", placeholder: "e.g. SaaS" },
  { key: "company", label: "Company", placeholder: "e.g. Acme" },
  { key: "title", label: "Job title", placeholder: "e.g. COO" },
] as const;
const SUGGESTIONS = ["SaaS", "Operations leaders", "United States"];

function activeSessionToken(): string {
  return window.localStorage.getItem("loqi_active_session_token") || "";
}

function LeadFilters({
  filters,
  hasFilters,
  query,
  onChange,
  onClear,
}: {
  filters: Record<string, string>;
  hasFilters: boolean;
  query: string;
  onChange: (next: Record<string, string>) => void;
  onClear: () => void;
}) {
  return (
    <aside className="sticky top-5 rounded-xl border border-outline-variant/20 bg-surface-lowest p-4 lg:top-20">
      <div className="mb-5 flex items-center justify-between">
        <h2 className="font-medium text-on-surface">Filters</h2>
        <button
          type="button"
          className="text-xs font-medium text-primary disabled:text-on-surface-variant/40"
          disabled={!hasFilters}
          onClick={onClear}
        >
          Clear all
        </button>
      </div>
      <div className="space-y-4">
        {FILTERS.map(({ key, label, placeholder }) => (
          <label key={key} className="block">
            <span className="mb-1.5 block text-xs font-medium text-on-surface-variant">
              {label}
            </span>
            <input
              aria-label={`Filter by ${label}`}
              value={filters[key]}
              placeholder={placeholder}
              onChange={(event) => onChange({ ...filters, q: query, [key]: event.target.value })}
              className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40 focus:border-primary/50"
            />
          </label>
        ))}
      </div>
      <p className="mt-5 border-t border-outline-variant/15 pt-4 text-xs leading-relaxed text-on-surface-variant/60">
        Filters match canonical lead fields and imported CSV metadata.
      </p>
    </aside>
  );
}

function LeadResultsTable({
  leads,
  selected,
  selectedOnPage,
  onToggleVisible,
  onToggleLead,
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
            return (
              <tr
                key={lead.id}
                className="border-b border-outline-variant/10 transition-colors last:border-0 hover:bg-surface-container-low/55"
              >
                <td className="px-4 py-3">
                  <input
                    aria-label={`Select ${name || lead.email || "lead"}`}
                    type="checkbox"
                    checked={selected.has(lead.id)}
                    onChange={() => onToggleLead(lead.id)}
                  />
                </td>
                <td className="px-3 py-3">
                  <p className="font-medium text-on-surface">{name || "Unnamed lead"}</p>
                  <p className="mt-0.5 text-xs text-on-surface-variant/65">
                    {lead.email || "No email recorded"}
                  </p>
                </td>
                <td className="px-3 py-3 text-on-surface-variant">
                  {lead.company || "—"}
                  {lead.website && (
                    <p className="mt-0.5 max-w-40 truncate text-xs text-on-surface-variant/55">
                      {lead.website}
                    </p>
                  )}
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ProviderRunStatus({
  run,
  discoveryId,
  error,
}: {
  run: DiscoveryData | null;
  discoveryId: string;
  error: string;
}) {
  if (error) {
    return (
      <div className="rounded-xl border border-error/30 bg-error/5 p-4 text-sm text-error">
        Provider search could not be loaded. Your lead-database results are still available.
      </div>
    );
  }
  if (!discoveryId) return null;

  const inProgress = !run || run.status === "queued" || run.status === "searching";
  const failed = run?.status === "failed" || run?.status === "cancelled";
  const providerNames = Object.keys(run?.providers || {});

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-outline-variant/20 bg-surface-container-low px-4 py-3 text-sm">
      <div className="flex items-center gap-2 text-on-surface-variant">
        <span className={`material-symbols-outlined text-[19px] ${inProgress ? "animate-spin text-primary" : failed ? "text-error" : "text-primary"}`}>
          {inProgress ? "progress_activity" : failed ? "error" : "check_circle"}
        </span>
        <span>
          {inProgress
            ? "Searching provider sources… workspace results remain available while this runs."
            : failed
              ? "The provider search did not complete."
              : `${run?.workspaceLeadResults.length || 0} provider result${run?.workspaceLeadResults.length === 1 ? "" : "s"} were saved to your canonical lead database${providerNames.length ? ` from ${providerNames.join(", ")}` : ""}.`}
        </span>
      </div>
      <Link href={`/discovery/${encodeURIComponent(discoveryId)}`} className="text-xs font-medium text-primary hover:underline">
        View research details
      </Link>
    </div>
  );
}

/**
 * The primary Discovery surface. Workspace leads come from the canonical lead
 * query; an explicit Search all sources click launches the existing durable
 * provider Discovery path. Both return canonical workspace_lead IDs.
 */
function WorkspaceLeadDiscovery() {
  const router = useRouter();
  const params = useSearchParams();
  const providerSearchEnabled = useBetaFeature("lead_search");
  const [workspaceLeads, setWorkspaceLeads] = useState<WorkspaceLeadRecord[]>([]);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [providerRun, setProviderRun] = useState<DiscoveryData | null>(null);
  const [providerError, setProviderError] = useState("");
  const [startingProviderSearch, setStartingProviderSearch] = useState(false);

  const query = params.get("q") || "";
  const page = Math.max(Number(params.get("page") || "1") || 1, 1);
  const providerDiscoveryId = params.get("provider_discovery") || "";
  const filters = useMemo(
    () => Object.fromEntries(FILTERS.map(({ key }) => [key, params.get(key) || ""])),
    [params],
  );

  const replaceQuery = (next: Record<string, string>, nextProviderDiscoveryId = providerDiscoveryId) => {
    const url = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => {
      if (value) url.set(key, value);
    });
    if (nextProviderDiscoveryId) url.set("provider_discovery", nextProviderDiscoveryId);
    router.replace(`/discovery${url.size ? `?${url.toString()}` : ""}`);
  };

  const changeSearch = (next: Record<string, string>) => {
    // A changed query is a different explicit search. Preserve the old run
    // durably in History rather than showing stale provider results for it.
    replaceQuery({ ...next, page: "1" }, "");
  };

  const loadWorkspaceLeads = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await listWorkspaceLeads(
        activeSessionToken(), query, page, filters, providerDiscoveryId,
      );
      setWorkspaceLeads(result.leads);
      setWorkspaceTotal(result.total);
    } catch {
      setWorkspaceLeads([]);
      setWorkspaceTotal(0);
      setError("Could not load leads. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadWorkspaceLeads();
    // URL state is this screen's read model; stable serialized filters avoid
    // a query for unrelated rerenders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, page, JSON.stringify(filters)]);

  useEffect(() => {
    if (!providerDiscoveryId) {
      setProviderRun(null);
      setProviderError("");
      return;
    }

    let active = true;
    let retryTimer: number | undefined;
    const refresh = async () => {
      try {
        const next = await fetchDiscoveryFresh(providerDiscoveryId);
        if (!active) return;
        setProviderRun(next);
        setProviderError("");
        if (next?.status === "queued" || next?.status === "searching") {
          retryTimer = window.setTimeout(() => void refresh(), 4000);
        } else if (next?.status === "completed") {
          // Provider results are now durable workspace leads. Reload the
          // server-paginated canonical set rather than adding a page-one
          // in-memory overlay.
          void loadWorkspaceLeads();
        }
      } catch {
        if (active) setProviderError("Provider results could not be loaded.");
      }
    };
    void refresh();
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [providerDiscoveryId]);

  const startProviderSearch = async () => {
    const requestedQuery = query.trim();
    if (!requestedQuery || startingProviderSearch || !providerSearchEnabled) return;
    setStartingProviderSearch(true);
    setProviderError("");
    try {
      const started = await startDiscoverySearch(requestedQuery, "manual");
      if (!started?.discoveryId) throw new Error("Provider search could not be started.");
      replaceQuery({ ...filters, q: requestedQuery, page: "1" }, started.discoveryId);
    } catch (caught) {
      setProviderError(caught instanceof Error ? caught.message : "Provider search could not be started.");
    } finally {
      setStartingProviderSearch(false);
    }
  };

  const selectedOnPage = workspaceLeads.length > 0 && workspaceLeads.every((lead) => selected.has(lead.id));
  const hasFilters = Boolean(query || Object.values(filters).some(Boolean));

  const toggleVisible = () => {
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
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
  };

  return (
    <main className="mx-auto w-full max-w-[1500px] space-y-7 px-5 py-8 md:px-8">
      <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div className="max-w-2xl">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary">Discovery</p>
          <h1 className="font-serif text-4xl tracking-tight text-on-surface md:text-5xl">Find the right leads</h1>
          <p className="mt-3 text-sm leading-relaxed text-on-surface-variant">
            Search your lead database and, when you choose, existing provider sources. Nothing is sourced until you explicitly search all sources.
          </p>
        </div>
        <Link
          href="/discovery/history"
          className="inline-flex items-center gap-2 self-start rounded-lg border border-outline-variant/25 bg-surface-lowest px-3 py-2 text-sm text-on-surface-variant transition-colors hover:border-primary/40 hover:text-primary lg:self-auto"
        >
          <span className="material-symbols-outlined text-[18px]">history</span>
          Research history
        </Link>
      </header>

      <form
        className="rounded-2xl border border-outline-variant/20 bg-surface-lowest p-3 shadow-sm"
        onSubmit={(event) => {
          event.preventDefault();
          void startProviderSearch();
        }}
      >
        <div className="flex items-center gap-3 rounded-xl bg-surface-container-low px-4 py-3 focus-within:ring-1 focus-within:ring-primary/40">
          <span className="material-symbols-outlined text-[24px] text-primary">search</span>
          <input
            aria-label="Search Discovery"
            className="min-w-0 flex-1 bg-transparent text-base text-on-surface outline-none placeholder:text-on-surface-variant/45 md:text-lg"
            value={query}
            placeholder="Search people, companies, titles, websites..."
            onChange={(event) => changeSearch({ ...filters, q: event.target.value })}
          />
          {query && (
            <button
              type="button"
              aria-label="Clear Discovery search"
              onClick={() => changeSearch({ ...filters, q: "" })}
              className="text-on-surface-variant/60 hover:text-on-surface"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          )}
          {providerSearchEnabled && (
            <button
              type="submit"
              disabled={!query.trim() || startingProviderSearch}
              className="shrink-0 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary disabled:opacity-45"
            >
              {startingProviderSearch ? "Starting…" : "Search all sources"}
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-2 pt-3">
          <span className="mr-1 text-xs font-medium text-on-surface-variant/60">Suggested for you</span>
          {SUGGESTIONS.map((suggestion) => (
            <button
              type="button"
              key={suggestion}
              onClick={() => changeSearch({ ...filters, q: suggestion })}
              className="rounded-full border border-outline-variant/20 bg-surface-container-low px-3 py-1.5 text-xs text-on-surface-variant transition-colors hover:border-primary/40 hover:text-primary"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </form>

      <ProviderRunStatus run={providerRun} discoveryId={providerDiscoveryId} error={providerError} />

      <div className="grid items-start gap-6 lg:grid-cols-[248px_minmax(0,1fr)]">
        <LeadFilters
          filters={filters}
          hasFilters={hasFilters}
          query={query}
          onChange={changeSearch}
          onClear={() => replaceQuery({}, "")}
        />

        <section className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 px-1">
            <p className="text-sm text-on-surface-variant">
              <span className="font-semibold text-on-surface">{workspaceTotal}</span> result{workspaceTotal === 1 ? "" : "s"}
            </p>
            {selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-primary">{selected.size} selected</span>
                <button
                  type="button"
                  className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary transition-opacity hover:opacity-90"
                  onClick={() => router.push(`/lead-intelligence?lead_ids=${encodeURIComponent([...selected].join(","))}`)}
                >
                  Analyze with Loqi
                </button>
                <button
                  type="button"
                  className="px-2 py-2 text-sm text-on-surface-variant hover:text-primary"
                  onClick={() => setSelected(new Set())}
                >
                  Clear selection
                </button>
              </div>
            )}
          </div>

          {error ? (
            <div className="rounded-xl border border-error/30 bg-error/5 p-6 text-center">
              <p className="font-medium text-error">{error}</p>
              <button type="button" onClick={() => void loadWorkspaceLeads()} className="mt-3 text-sm text-primary hover:underline">
                Try again
              </button>
            </div>
          ) : loading ? (
            <div className="flex min-h-64 items-center justify-center rounded-xl border border-outline-variant/20 bg-surface-lowest text-sm text-on-surface-variant">
              <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
              Loading Discovery results…
            </div>
          ) : workspaceLeads.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant/30 bg-surface-lowest p-8 text-center">
              <span className="material-symbols-outlined mb-3 text-3xl text-on-surface-variant/45">group_off</span>
              <p className="font-medium text-on-surface">
                {hasFilters ? "No leads match these filters." : "Your lead database is empty."}
              </p>
              <p className="mt-1 max-w-sm text-sm text-on-surface-variant">
                {hasFilters
                  ? "Try broadening your search or clear a filter."
                  : "Import a CSV in Lead Database, or explicitly search provider sources above."}
              </p>
              {!hasFilters && (
                <Link href="/contacts" className="mt-4 text-sm font-medium text-primary hover:underline">
                  Open Lead Database
                </Link>
              )}
            </div>
          ) : (
            <>
              <LeadResultsTable
                leads={workspaceLeads}
                selected={selected}
                selectedOnPage={selectedOnPage}
                onToggleVisible={toggleVisible}
                onToggleLead={toggleLead}
              />
              {workspaceTotal > PAGE_SIZE && (
                <nav className="flex items-center justify-between pt-2" aria-label="Lead results pagination">
                  <button
                    type="button"
                    disabled={page === 1}
                    onClick={() => replaceQuery({ ...filters, q: query, page: String(page - 1) })}
                    className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-on-surface-variant">Page {page} of {Math.ceil(workspaceTotal / PAGE_SIZE)}</span>
                  <button
                    type="button"
                    disabled={page * PAGE_SIZE >= workspaceTotal}
                    onClick={() => replaceQuery({ ...filters, q: query, page: String(page + 1) })}
                    className="rounded-lg border border-outline-variant/25 px-3 py-2 text-sm text-on-surface disabled:opacity-40"
                  >
                    Next
                  </button>
                </nav>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

export default function DiscoveryPage() {
  const params = useSearchParams();
  // Campaign research remains an existing automated flow. It intentionally
  // stays outside the Beta's explicit manual provider-search capability.
  if (parseDiscoveryMode(params).mode === "campaign_attach") return <DiscoveryHistory />;
  return <WorkspaceLeadDiscovery />;
}
