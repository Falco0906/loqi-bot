"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  analyzeWorkspaceLeads,
  generateWorkspaceLeadStrategyDrafts,
} from "../../../lib/api";

type Analysis = Awaited<ReturnType<typeof analyzeWorkspaceLeads>>;
type GeneratedDrafts = Awaited<ReturnType<typeof generateWorkspaceLeadStrategyDrafts>>;

export default function LeadIntelligencePage() {
  const params = useSearchParams();
  const ids = (params.get("lead_ids") || "").split(",").filter(Boolean);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [generatedDrafts, setGeneratedDrafts] = useState<GeneratedDrafts | null>(null);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [copyMessage, setCopyMessage] = useState("");

  const analyze = async () => {
    setBusy(true);
    setError("");
    try {
      const token = localStorage.getItem("loqi_active_session_token") || "";
      setAnalysis(await analyzeWorkspaceLeads(token, ids));
      setGeneratedDrafts(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    setGenerating(true);
    setError("");
    try {
      const token = localStorage.getItem("loqi_active_session_token") || "";
      setGeneratedDrafts(await generateWorkspaceLeadStrategyDrafts(token, ids));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Strategy generation failed");
    } finally {
      setGenerating(false);
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

      <button disabled={busy || generating} onClick={() => void analyze()} className="rounded-lg bg-primary px-4 py-2 text-on-primary disabled:opacity-50">
        {busy ? "Analyzing selected leads…" : "Analyze with Loqi"}
      </button>
      {analysis && <button disabled={busy || generating} onClick={() => void generate()} className="rounded-lg border border-primary px-4 py-2 text-primary disabled:opacity-50">
        {generating ? "Generating strategy & draft…" : "Generate strategy & draft"}
      </button>}
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
