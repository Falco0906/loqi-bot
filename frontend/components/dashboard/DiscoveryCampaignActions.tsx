"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { addLeadToCampaign, ApiError, getCampaign, getCampaignSummary } from "../../lib/api";
import { campaignContainsLeadIds } from "../../lib/campaign-attachment-reconciliation";

/** Campaign selection actions reuse canonical campaign APIs; they never approve or analyze leads. */
export default function DiscoveryCampaignActions({ leadIds, campaignContext, workspaceId = "", onComplete, onBusy }: {
  leadIds: string[];
  campaignContext: string | null;
  workspaceId?: string;
  onComplete: (leadIds: string[]) => void;
  onBusy: (busy: boolean) => void;
}) {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<Array<{ id: string; name: string }>>([]);
  const [destination, setDestination] = useState("");
  const [contextName, setContextName] = useState("");
  const [contextError, setContextError] = useState("");
  const [contextLoading, setContextLoading] = useState(false);
  const [mode, setMode] = useState<"existing" | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [message, setMessage] = useState("");
  const [uncertain, setUncertain] = useState<{ campaignId: string; leadIds: string[] } | null>(null);
  const [completedId, setCompletedId] = useState("");
  const token = () => window.localStorage.getItem("loqi_active_session_token") || "";

  useEffect(() => {
    let active = true;
    setContextError(""); setContextName(""); setDestination(""); setMode(null);
    if (campaignContext === null) { setContextLoading(false); return; }
    if (!campaignContext) { setContextLoading(false); setContextError("This link has no destination campaign. Open a campaign or choose another below."); return; }
    setContextLoading(true);
    getCampaign(token(), campaignContext, workspaceId).then((result) => {
      if (!active) return;
      if (!result.ok || !result.campaign?.id) throw new Error("Campaign unavailable");
      setDestination(String(result.campaign.id));
      setContextName(String(result.campaign.name || "Campaign"));
    }).catch(() => {
      if (active) setContextError("This campaign is unavailable in the selected workspace. Choose another campaign below.");
    }).finally(() => { if (active) setContextLoading(false); });
    return () => { active = false; };
  }, [campaignContext, workspaceId]);

  function lock(value: boolean) { if (!mounted.current) return; busyRef.current = value; setBusy(value); onBusy(value); }

  function chooseNew() {
    if (busyRef.current || loading || contextLoading || !leadIds.length) return;
    const params = new URLSearchParams({ workspace_id: workspaceId, lead_ids: leadIds.join(","), return: "discovery" });
    router.push(`/campaigns/new?${params.toString()}`);
  }

  async function chooseExisting() {
    if (busyRef.current || loading || contextLoading) return;
    setMode("existing"); setLoading(true); setMessage("");
    try {
      const result = await getCampaignSummary(token(), workspaceId);
      if (!mounted.current) return;
      if (!result.ok) throw new Error("Campaign list unavailable");
      setCampaigns(result.campaigns.filter((campaign) => campaign.status !== "archived"));
    } catch { if (mounted.current) setMessage("Campaigns could not be loaded. Please open the selector again."); }
    finally { if (mounted.current) setLoading(false); }
  }

  async function checkAttachment(campaignId: string, ids: string[]): Promise<boolean> {
    const result = await getCampaign(token(), campaignId, workspaceId);
    if (!mounted.current) return false;
    if (result.ok && campaignContainsLeadIds(result.campaign, ids)) {
      setMessage(`${ids.length} selected lead${ids.length === 1 ? "" : "s"} attached to campaign.`);
      setCompletedId(campaignId); setUncertain(null); setMode(null); onComplete(ids); lock(false);
      return true;
    }
    return false;
  }

  async function submit() {
    if (busyRef.current || !leadIds.length || contextLoading || loading) return;
    if (mode !== "existing" || !destination) return;
    const ids = [...leadIds];
    lock(true); setMessage(""); setCompletedId("");
    // Wait for every request to settle before reconciling a partial/lost response.
    const outcomes = await Promise.allSettled(ids.map((id) => addLeadToCampaign(token(), destination, { id, workspace_lead_id: id }, undefined, workspaceId)));
    if (!mounted.current) return;
    if (outcomes.every((outcome) => outcome.status === "fulfilled" && outcome.value.ok)) {
      setMessage(`${ids.length} selected lead${ids.length === 1 ? "" : "s"} attached to campaign.`);
      setCompletedId(destination); setMode(null); onComplete(ids); lock(false); return;
    }
    try { if (await checkAttachment(destination, ids)) return; } catch { /* Remain explicitly unknown; never retry POSTs. */ }
    if (!mounted.current) return;
    const unknown = outcomes.some((outcome) => outcome.status === "fulfilled"
      ? !outcome.value.ok
      : !(outcome.reason instanceof ApiError && outcome.reason.status < 500));
    if (unknown) {
      setUncertain({ campaignId: destination, leadIds: ids });
      setMessage("Attachment outcome is not yet confirmed. Check campaign status before taking another action.");
    } else {
      setMessage("Some selected leads could not be attached. Check the campaign before trying again; existing attachments are preserved.");
      lock(false);
    }
  }

  return <div className="space-y-3 text-sm">
    {contextLoading && <p role="status">Checking destination campaign…</p>}
    {contextName && <p>Adding leads to <strong>{contextName}</strong>. Search explicitly, then select leads below.</p>}
    {contextError && <p role="alert" className="text-error">{contextError} <Link href="/discovery" className="underline">Leave campaign context</Link></p>}
    {leadIds.length > 0 && <div className="flex flex-wrap gap-2">
      <button type="button" disabled={busy || loading || contextLoading} onClick={() => void chooseExisting()} className="rounded-lg border border-outline-variant/25 px-3 py-2 disabled:opacity-40">Add to existing campaign</button>
      <button type="button" disabled={busy || loading || contextLoading} onClick={chooseNew} className="rounded-lg border border-outline-variant/25 px-3 py-2 disabled:opacity-40">Create campaign with selected leads</button>
    </div>}
    {mode && leadIds.length > 0 && <form onSubmit={(event) => { event.preventDefault(); void submit(); }} className="flex flex-wrap items-center gap-2">
      <select aria-label="Destination campaign" value={destination} disabled={busy || loading} onChange={(event) => setDestination(event.target.value)} className="rounded-lg bg-surface-container-low px-3 py-2">
        <option value="">{loading ? "Loading campaigns…" : "Choose a campaign"}</option>
        {contextName && !campaigns.some((campaign) => campaign.id === destination) && <option value={destination}>{contextName}</option>}
        {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}
      </select>
      <button type="submit" disabled={busy || loading || !destination} className="rounded-lg bg-primary px-3 py-2 text-on-primary disabled:opacity-40">{busy ? message ? "Outcome unconfirmed" : "Saving selected leads…" : "Attach selected leads"}</button>
      <button type="button" disabled={busy} onClick={() => setMode(null)}>Cancel</button>
      {mode === "existing" && !loading && !campaigns.length && !contextName && <span>No campaigns yet. Create one with your selected leads.</span>}
    </form>}
    {message && <p role="status">{message} {completedId && <Link href={`/campaigns/${completedId}?workspace_id=${encodeURIComponent(workspaceId)}`} className="text-primary underline">View campaign</Link>} {busy && !uncertain && <Link href={`/campaigns?workspace_id=${encodeURIComponent(workspaceId)}`} className="text-primary underline">Open Campaigns</Link>}</p>}
    {uncertain && <button type="button" disabled={loading} onClick={async () => {
      if (loading) return;
      setLoading(true);
      try { if (!await checkAttachment(uncertain.campaignId, uncertain.leadIds)) setMessage("Not all attachments are confirmed yet. No additional attachment requests have been sent."); }
      catch { setMessage("Campaign status is unavailable. No additional attachment requests have been sent."); }
      finally { setLoading(false); }
    }} className="text-primary underline">Check attachment status</button>}
  </div>;
}
