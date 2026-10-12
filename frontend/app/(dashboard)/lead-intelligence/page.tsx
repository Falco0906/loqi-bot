"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  analyzeWorkspaceLeads,
  generateWorkspaceLeadStrategyDrafts,
  recoverWorkspaceLeadGeneration,
  ApiError,
} from "../../../lib/api";
import { observeLeadGeneration } from "../../../lib/lead-generation-recovery";
import { generationMatchesSelection } from "../../../lib/lead-generation-recovery";
import { useIntelligenceWorkspace } from "../../../hooks/useIntelligenceWorkspace";

type Analysis = Awaited<ReturnType<typeof analyzeWorkspaceLeads>>;
type GeneratedDrafts = Awaited<ReturnType<typeof generateWorkspaceLeadStrategyDrafts>>;

function LeadIntelligenceWorkspace({ ids, workspaceId }: { ids: string[]; workspaceId: string }) {
  const params = useSearchParams();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [generatedDrafts, setGeneratedDrafts] = useState<GeneratedDrafts | null>(null);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [copyMessage, setCopyMessage] = useState("");
  const [generationMessage, setGenerationMessage] = useState("");
  const [generationPending, setGenerationPending] = useState(false);
  const [requestUnknown, setRequestUnknown] = useState(false);
  const requestKey = useRef("");
  const actionPending = useRef(false);
  const observer = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const analysisController = useRef<AbortController | null>(null);
  const urlKey = params.get("generation_key") || "";

  const reconcile = async (key: string) => {
    if (!mounted.current) return;
    observer.current?.abort();
    const controller = new AbortController();
    observer.current = controller;
    setGenerating(true);
    try {
      const outcome = await observeLeadGeneration(
        () => recoverWorkspaceLeadGeneration(key, controller.signal, workspaceId),
        (state) => {
          if (!mounted.current || controller.signal.aborted) return;
          if (!generationMatchesSelection(state, ids)) throw new ApiError("This generation belongs to a different lead selection. Start a new generation explicitly.", 409);
          setRequestUnknown(false);
          setGeneratedDrafts(state);
          if (state.analysis) setAnalysis(state.analysis);
          const pending = ["queued", "running"].includes(state.status);
          setGenerationPending(pending);
          setGenerationMessage(pending ? `${state.stage || "Generation is processing"} · ${state.results.length} results saved` : "");
          if (state.status === "failed" || state.status === "cancelled") setError(state.error || "Generation did not complete. Saved results remain available.");
        }, controller.signal,
      );
      if (!controller.signal.aborted && outcome === "paused") setGenerationMessage("Generation may still be processing. Check status to recover saved results.");
    } catch (caught) {
      if (!controller.signal.aborted) {
        if (caught instanceof ApiError && caught.status < 500 && caught.status !== 404) setGenerationPending(false);
        if (caught instanceof ApiError && caught.status === 404) setRequestUnknown(true);
        setError(caught instanceof Error ? caught.message : "Generation status is unavailable.");
      }
    } finally {
      if (!controller.signal.aborted) setGenerating(false);
    }
  };

  useEffect(() => {
    mounted.current = true;
    if (requestKey.current !== urlKey) {
      requestKey.current = urlKey;
      actionPending.current = false;
      setBusy(false);
      setGeneratedDrafts(null);
      setGenerationPending(false);
      setGenerating(false);
      setRequestUnknown(false);
      setGenerationMessage("");
    }
    if (urlKey) {
      requestKey.current = urlKey;
      setGenerationPending(true);
      void reconcile(urlKey); // Read-only recovery; never starts AI work.
    }
    return () => { mounted.current = false; observer.current?.abort(); analysisController.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey]);

  const analyze = async () => {
    if (actionPending.current || generationPending) return;
    actionPending.current = true;
    setBusy(true);
    setError("");
    const controller = new AbortController();
    analysisController.current = controller;
    try {
      const token = localStorage.getItem("loqi_active_session_token") || "";
      const result = await analyzeWorkspaceLeads(token, ids, controller.signal, workspaceId);
      if (!mounted.current || controller.signal.aborted) return;
      setAnalysis(result);
      setGeneratedDrafts(null);
    } catch (caught) {
      if (!mounted.current || controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Analysis failed");
    } finally {
      if (mounted.current && !controller.signal.aborted) { actionPending.current = false; setBusy(false); }
    }
  };

  const generate = async (recoverRequest = false) => {
    if (actionPending.current || generating || (generationPending && !recoverRequest)) return;
    actionPending.current = true;
    setGenerating(true);
    setError("");
    if (!recoverRequest) requestKey.current = crypto.randomUUID();
    const generationKey = requestKey.current;
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("generation_key", requestKey.current);
      window.history.replaceState(window.history.state, "", url.toString());
      setGenerationPending(true);
      const token = localStorage.getItem("loqi_active_session_token") || "";
      const generated = await generateWorkspaceLeadStrategyDrafts(token, ids, requestKey.current, workspaceId);
      if (!mounted.current || generationKey !== requestKey.current) return;
      setGeneratedDrafts(generated);
      await reconcile(requestKey.current);
    } catch (caught) {
      if (!mounted.current || generationKey !== requestKey.current) return;
      if (caught instanceof ApiError && caught.status < 500) {
        setGenerationPending(false);
        setError(caught.message);
      } else {
        setRequestUnknown(true);
        setGenerationMessage("Generation outcome is unknown. Checking saved results…");
        await reconcile(requestKey.current);
      }
    } finally {
      if (mounted.current && generationKey === requestKey.current) { actionPending.current = false; setGenerating(false); }
    }
  };

  const copyDraft = async (subject: string, body: string) => {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      setCopyMessage("Draft copied to clipboard.");
    } catch {
      setCopyMessage("Could not copy the draft. Select and copy the text manually.");
    }
  };

  if (!ids.length) {
    return <main className="p-8"><h1 className="text-3xl font-semibold">Lead Intelligence</h1><p className="mt-4">Select leads in Discover before analyzing.</p></main>;
  }

  return (
    <main className="p-8 space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Lead Intelligence</h1>
        <p className="text-on-surface-variant">{ids.length} selected lead{ids.length === 1 ? "" : "s"}. Analysis starts only when you choose it.</p>
      </header>

      <button disabled={busy || generating || generationPending} onClick={() => void analyze()} className="rounded-lg bg-primary px-4 py-2 text-on-primary disabled:opacity-50">
        {busy ? "Analyzing selected leads…" : "Analyze with Loqi"}
      </button>
      {analysis && <button disabled={busy || generating || generationPending} onClick={() => void generate()} className="rounded-lg border border-primary px-4 py-2 text-primary disabled:opacity-50">
        {generating ? "Generating strategy & draft…" : "Generate strategy & draft"}
      </button>}
      {generationMessage && <p role="status" className="text-sm text-on-surface-variant">{generationMessage}</p>}
      {generationPending && !generating && <button onClick={() => void reconcile(requestKey.current)} className="rounded border px-3 py-1 text-sm">Check generation status</button>}
      {requestUnknown && !generating && <button onClick={() => void generate(true)} className="rounded border px-3 py-1 text-sm">Recover generation request</button>}
      {error && <p className="text-error">{error}</p>}
      {copyMessage && <p className="text-sm text-on-surface-variant">{copyMessage}</p>}

      {analysis?.business_guidance && <section className="rounded-xl border p-5 space-y-3">
        <h2 className="font-semibold">Business guidance</h2>
        <p className="text-sm text-on-surface-variant">{analysis.business_guidance.note}</p>
        {analysis.business_guidance.items.length ? <ul className="space-y-2">
          {analysis.business_guidance.items.map((item) => <li key={item.id} className="text-sm"><b>{item.title || item.category}</b>{item.summary ? ` — ${item.summary}` : ""}</li>)}
        </ul> : <p className="text-sm text-on-surface-variant">No matching workspace guidance is available.</p>}
      </section>}

      {analysis?.results.map((result) => {
        const assessment = result.derived_assessment;
        return <article key={result.lead.id} className="rounded-xl border p-5 space-y-5">
          <header>
            <h2 className="font-semibold">{result.lead.first_name} {result.lead.last_name} · {result.lead.company}</h2>
            <p className="text-sm text-on-surface-variant">{result.lead.title || "No title recorded"}</p>
          </header>
          {result.status === "failed" ? <p className="text-error">{result.error}</p> : <>
            <section><h3 className="font-medium">Derived assessment</h3><p className="mt-1 uppercase text-primary text-sm">{assessment?.priority} priority · {assessment?.icp_fit}/100 ICP fit</p><ul className="mt-2 list-disc pl-5 text-sm">{assessment?.why_this_lead.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>
            <section><h3 className="font-medium">Recommended approach</h3><p className="mt-1 text-sm">{assessment?.recommended_approach || "No specific approach is justified by the available lead data."}</p></section>
            <section><h3 className="font-medium">Facts</h3>{result.facts?.length ? <ul className="mt-2 space-y-1 text-sm">{result.facts.map((fact) => <li key={fact.label}><b>{fact.label}:</b> {fact.value}</li>)}</ul> : <p className="text-sm text-on-surface-variant">No additional canonical facts are available.</p>}</section>
            <section><h3 className="font-medium">Observed signals</h3>{result.observed_signals?.length ? <ul className="mt-2 space-y-1 text-sm">{result.observed_signals.map((signal) => <li key={`${signal.type}-${signal.detected_at}`}><b>{signal.label || signal.type}</b>{signal.source ? ` · ${signal.source}` : ""}</li>)}</ul> : <p className="text-sm text-on-surface-variant">No persisted signals are available for this lead.</p>}</section>
            {generatedDrafts && <GeneratedDraft leadId={result.lead.id} drafts={generatedDrafts} onCopy={copyDraft} />}
          </>}
        </article>;
      })}
    </main>
  );
}

export default function LeadIntelligencePage() {
  const params = useSearchParams();
  const ids = [...new Set((params.get("lead_ids") || "").split(",").map((id) => id.trim()).filter(Boolean))].sort();
  const context = useIntelligenceWorkspace(params.get("workspace_id") || "");
  if (!context.workspace) return <main className="p-8" role={context.error ? "alert" : "status"}>{context.error || "Loading your workspace…"}</main>;
  return <LeadIntelligenceWorkspace key={`${context.scope}:${ids.join(",")}`} ids={ids} workspaceId={context.workspace} />;
}

function GeneratedDraft({
  leadId,
  drafts,
  onCopy,
}: {
  leadId: string;
  drafts: GeneratedDrafts;
  onCopy: (subject: string, body: string) => Promise<void>;
}) {
  const generated = drafts.results.find((item) => item.lead_id === leadId);
  if (!generated) return null;
  if (generated.status === "failed" || !generated.strategy || !generated.outreach) {
    return <p className="text-error">{generated.error || "Strategy generation failed."}</p>;
  }
  return <section className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-4">
    <p className="text-xs font-semibold uppercase tracking-wide text-primary">AI-generated strategy and outreach draft</p>
    <div><h3 className="font-medium">AI strategy</h3><p className="mt-1 text-sm"><b>Why this lead:</b> {generated.strategy.relevance_summary}</p><p className="mt-1 text-sm"><b>Recommended angle:</b> {generated.strategy.recommended_angle}</p><p className="mt-1 text-sm"><b>Key message:</b> {generated.strategy.key_message}</p><p className="mt-1 text-sm"><b>Next action:</b> {generated.strategy.next_action}</p><p className="mt-1 text-sm"><b>Avoid:</b> {generated.strategy.things_to_avoid.join("; ")}</p></div>
    <div><h3 className="font-medium">Outreach draft</h3><p className="mt-1 text-sm"><b>Subject:</b> {generated.outreach.subject}</p><p className="mt-2 whitespace-pre-wrap text-sm">{generated.outreach.body}</p><button onClick={() => void onCopy(generated.outreach!.subject, generated.outreach!.body)} className="mt-3 rounded border px-3 py-1 text-sm">Copy draft</button></div>
    <div><h3 className="font-medium">Evidence used</h3>{generated.evidence_used?.length ? <ul className="mt-1 list-disc pl-5 text-sm">{generated.evidence_used.map((item) => <li key={`${item.source_type}-${item.statement}`}>{item.statement}</li>)}</ul> : <p className="text-sm text-on-surface-variant">No evidence citations were returned.</p>}</div>
  </section>;
}
