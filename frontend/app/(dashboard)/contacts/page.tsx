"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { importLeadCsv, listWorkspaceLeads, previewLeadCsv, type WorkspaceLeadRecord } from "../../../lib/api";

const token = () => typeof window === "undefined" ? "" : localStorage.getItem("loqi_active_session_token") || "";
const FIELDS = ["first_name", "last_name", "name", "email", "company", "website", "title", "linkedin_url", "location", "industry", "company_size", "phone"];
const PAGE_SIZE = 50;
type CsvPreview = Awaited<ReturnType<typeof previewLeadCsv>>;
const leadName = (lead: WorkspaceLeadRecord) => `${lead.first_name} ${lead.last_name}`.trim() || "—";
const errorMessage = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

export default function ContactsPage() {
  const [leads, setLeads] = useState<WorkspaceLeadRecord[]>([]); const [search, setSearch] = useState(""); const [page, setPage] = useState(1); const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set()); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [csv, setCsv] = useState(""); const [preview, setPreview] = useState<CsvPreview | null>(null); const [mapping, setMapping] = useState<Record<string, string>>({});
  const [mappingOpen, setMappingOpen] = useState(false); const [preparing, setPreparing] = useState(false); const [importing, setImporting] = useState(false); const [summary, setSummary] = useState("");

  const load = useCallback(async (nextPage = page, nextSearch = search) => {
    setLoading(true);
    try { const response = await listWorkspaceLeads(token(), nextSearch, nextPage); setLeads(response.leads); setTotal(response.total); setError(""); }
    catch (loadError) { setLeads([]); setTotal(0); setError(errorMessage(loadError, "Could not load your lead database.")); }
    finally { setLoading(false); }
  }, [page, search]);
  useEffect(() => { void load(); }, [load]);

  const inspect = useCallback(async (content = csv, nextMapping = mapping) => {
    if (!content) return; setPreparing(true);
    try { const result = await previewLeadCsv(token(), content, nextMapping); setPreview(result); setMapping(result.mapping); setSummary(""); setError(""); }
    catch (previewError) { setPreview(null); setError(errorMessage(previewError, "CSV could not be parsed.")); }
    finally { setPreparing(false); }
  }, [csv, mapping]);

  const upload = async (file?: File) => {
    if (!file) return; const content = await file.text(); setCsv(content); setPreview(null); setMapping({}); setMappingOpen(false); setSummary(""); setError("");
    // A conventional CSV gets the suggested mapping and preview immediately.
    await inspect(content, {});
  };
  const confirm = async () => {
    if (!preview) return; setImporting(true); setError("");
    try {
      const finalPreview = await previewLeadCsv(token(), csv, mapping); const outcome = await importLeadCsv(token(), finalPreview.rows);
      setSummary(`${outcome.imported} imported · ${outcome.duplicates.length} duplicates skipped · ${finalPreview.invalid_rows.length + outcome.invalid.length} invalid`);
      setPreview(null); setCsv(""); setMapping({}); setMappingOpen(false); setSearch(""); setPage(1); await load(1, "");
    } catch (importError) { setError(errorMessage(importError, "Import could not be completed. No rows were retried automatically.")); }
    finally { setImporting(false); }
  };
  const allVisible = leads.length > 0 && leads.every((lead) => selected.has(lead.id)); const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visibleRange = useMemo(() => !total ? "0 leads" : `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total} leads`, [page, total]);
  const toggleAll = () => setSelected((current) => { const next = new Set(current); leads.forEach((lead) => allVisible ? next.delete(lead.id) : next.add(lead.id)); return next; });

  return <main className="mx-auto max-w-[1500px] space-y-6 p-5 sm:p-8">
    <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Workspace data</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Lead Database</h1><p className="mt-2 text-sm text-on-surface-variant">Import, search, and select durable leads in your selected workspace.</p></div>{selected.size > 0 && <div className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-primary">{selected.size} selected</div>}</header>
    <section className="rounded-2xl border border-outline-variant/50 bg-surface p-4 shadow-sm sm:p-5"><div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><h2 className="font-medium">Import leads from CSV</h2><p className="mt-1 text-sm text-on-surface-variant">Upload a header-based CSV. Loqi suggests the mapping and waits for your confirmation before anything is saved.</p></div><label className="inline-flex shrink-0 cursor-pointer items-center justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-on-primary"><span>{preparing ? "Reading CSV…" : "Upload CSV"}</span><input type="file" accept=".csv,text/csv" className="hidden" disabled={preparing || importing} onChange={(event) => void upload(event.target.files?.[0])}/></label></div>
      {preview && <div className="mt-5 rounded-xl border border-outline-variant/50 bg-surface-container-low p-4 sm:p-5"><div className="flex flex-col gap-3 sm:flex-row sm:justify-between"><div><h3 className="font-medium">Ready to import</h3><p className="mt-1 text-sm text-on-surface-variant">{preview.total_rows} detected · {preview.valid_rows} ready · {preview.invalid_rows.length} invalid</p></div><button type="button" className="text-left text-sm font-medium text-primary hover:underline" onClick={() => setMappingOpen((open) => !open)}>{mappingOpen ? "Hide column mapping" : "Review column mapping"}</button></div>
        {mappingOpen && <div className="mt-4 grid gap-2 border-t border-outline-variant/40 pt-4 sm:grid-cols-2">{preview.headers.map((header) => <label key={header} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-3 text-sm"><span className="truncate text-on-surface-variant" title={header}>{header}</span><select className="rounded-md border border-outline-variant bg-surface px-2 py-1.5" value={mapping[header] || ""} onChange={(event) => setMapping((current) => ({ ...current, [header]: event.target.value }))}><option value="">Do not import</option>{FIELDS.map((field) => <option key={field} value={field}>{field.replaceAll("_", " ")}</option>)}</select></label>)}<p className="sm:col-span-2 pt-2 text-xs text-on-surface-variant">Unmapped columns remain in the source file: {preview.unmapped_columns.join(", ") || "none"}.</p></div>}
        {preview.invalid_rows.length > 0 && <p className="mt-4 rounded-lg border border-error/30 bg-error/5 p-3 text-sm text-error">{preview.invalid_rows.length} row{preview.invalid_rows.length === 1 ? "" : "s"} will be skipped because they need at least a name, email, or company.</p>}
        <div className="mt-5 flex flex-wrap items-center gap-3"><button disabled={importing || !preview.valid_rows} onClick={() => void confirm()} className="rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-on-primary disabled:cursor-not-allowed disabled:opacity-50">{importing ? `Importing ${preview.valid_rows} leads…` : `Confirm import ${preview.valid_rows} leads`}</button><button type="button" className="text-sm text-on-surface-variant hover:text-on-surface" disabled={importing} onClick={() => { setPreview(null); setCsv(""); setMapping({}); }}>Cancel</button></div>
      </div>}</section>
    {error && <section role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-error/30 bg-error/5 p-4 text-sm text-error"><span>{error}</span><button className="rounded-md border border-error/40 px-3 py-1.5" onClick={() => void load()}>Try again</button></section>}
    {summary && <section className="rounded-xl border border-primary/30 bg-primary/10 p-4 text-sm text-primary">Import complete: {summary}</section>}
    <section className="overflow-hidden rounded-2xl border border-outline-variant/50 bg-surface shadow-sm"><div className="flex flex-col gap-3 border-b border-outline-variant/50 p-4 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-medium">Your leads</h2><p className="mt-0.5 text-sm text-on-surface-variant">{loading ? "Loading durable lead records…" : visibleRange}</p></div><input className="w-full rounded-lg border border-outline-variant bg-surface-container-low px-3 py-2 text-sm sm:w-80" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search name, email, company, title…" aria-label="Search leads"/></div>
      {loading ? <div className="p-10 text-center text-sm text-on-surface-variant">Loading leads…</div> : error ? <div className="p-10 text-center text-sm text-on-surface-variant">Your lead database could not be loaded.</div> : leads.length === 0 ? <div className="p-12 text-center"><p className="font-medium">{search ? "No leads match your search." : "No leads yet."}</p><p className="mt-2 text-sm text-on-surface-variant">{search ? "Try another name, company, title, or email." : "Upload a CSV to add the first durable leads to this workspace."}</p></div> : <><div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-surface-container-low text-xs uppercase tracking-wide text-on-surface-variant"><tr><th className="w-12 px-4 py-3"><input aria-label="Select all visible leads" type="checkbox" checked={allVisible} onChange={toggleAll}/></th><th className="px-3 py-3 font-medium">Name</th><th className="px-3 py-3 font-medium">Title</th><th className="px-3 py-3 font-medium">Company</th><th className="px-3 py-3 font-medium">Email</th><th className="px-3 py-3 font-medium">Location</th><th className="px-4 py-3 font-medium">Industry</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id} className="border-t border-outline-variant/35 hover:bg-surface-container-low/60"><td className="px-4 py-3"><input aria-label={`Select ${leadName(lead)}`} type="checkbox" checked={selected.has(lead.id)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(lead.id) ? next.delete(lead.id) : next.add(lead.id); return next; })}/></td><td className="px-3 py-3 font-medium">{leadName(lead)}</td><td className="px-3 py-3 text-on-surface-variant">{lead.title || "—"}</td><td className="px-3 py-3">{lead.company || "—"}</td><td className="px-3 py-3 text-on-surface-variant">{lead.email || "—"}</td><td className="px-3 py-3 text-on-surface-variant">{lead.location || "—"}</td><td className="px-4 py-3 text-on-surface-variant">{lead.industry || "—"}</td></tr>)}</tbody></table></div>{pages > 1 && <nav aria-label="Lead database pagination" className="flex items-center justify-between border-t border-outline-variant/50 px-4 py-3"><button disabled={page === 1} onClick={() => setPage((current) => current - 1)} className="rounded-md border border-outline-variant px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50">Previous</button><span className="text-sm text-on-surface-variant">Page {page} of {pages}</span><button disabled={page >= pages} onClick={() => setPage((current) => current + 1)} className="rounded-md border border-outline-variant px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50">Next</button></nav>}</>}</section>
  </main>;
}
