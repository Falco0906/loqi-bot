"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCampaignWorkspace } from "../../../../hooks/useCampaignWorkspace";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import AppPage from "../../../../components/primitives/AppPage";
import { saveCampaign } from "../../../../lib/api";
import { toast } from "../../../../components/shared/Toast";
import { invalidateClientCache, scopedKey } from "../../../../lib/client-cache";
const ACTIVE_SESSION_KEY = "loqi_active_session_token";
const HANDOFF_TTL_MS = 30 * 60 * 1000;

const campaignLeadHandoffKey = (sessionToken: string, discoveryId: string) =>
  `loqi_pending_campaign_leads:${sessionToken}:${discoveryId}`;

type CampaignLeadHandoff = {
  discovery_id: string;
  session_token: string;
  created_at: number;
  leads: Record<string, unknown>[];
};

export default function NewCampaignPage() {
  const params = useSearchParams();
  const context = useCampaignWorkspace(params.get("workspace_id") || "");
  if (!context.workspace) return <main role={context.error ? "alert" : "status"} className="p-8">{context.error || "Loading your workspace…"} {context.error && <button type="button" onClick={context.retry}>Retry</button>}</main>;
  return <NewCampaignForm key={`${context.scope}:${params.get("lead_ids") || params.get("discovery") || ""}`} workspaceId={context.workspace} />;
}

function NewCampaignForm({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const discoveryId = searchParams?.get("discovery") || "";
  const creationKey = useRef(searchParams?.get("creation_key") || "");
  const savingRef = useRef(false);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingLeads, setPendingLeads] = useState<Record<string, unknown>[]>([]);
  // Unified Discovery passes canonical IDs only. The creation API authorizes
  // every reference in this workspace; URL parameters are not proof of access.
  const selectedIds = searchParams.get("lead_ids");
  const selectedLeads = selectedIds !== null
    ? [...new Set(selectedIds.split(",").map((id) => id.trim()).filter(Boolean))].map((id) => ({ id, workspace_lead_id: id }))
    : pendingLeads;
  const emptySelection = selectedIds !== null && selectedLeads.length === 0;

  useEffect(() => {
    const discoveryEntry = Boolean(discoveryId && searchParams?.get("return") === "discovery");
    const token = localStorage.getItem(ACTIVE_SESSION_KEY) || "";
    if (!discoveryEntry) {
      setPendingLeads([]);
      return;
    }
    try {
      const key = campaignLeadHandoffKey(token, discoveryId);
      const raw = sessionStorage.getItem(key);
      const handoff = raw ? JSON.parse(raw) as CampaignLeadHandoff : null;
      const valid = handoff
        && handoff.discovery_id === discoveryId
        && handoff.session_token === token
        && Date.now() - handoff.created_at >= 0
        && Date.now() - handoff.created_at <= HANDOFF_TTL_MS
        && Array.isArray(handoff.leads);
      if (valid) setPendingLeads(handoff.leads);
      else {
        sessionStorage.removeItem(key);
        setPendingLeads([]);
      }
    } catch {
      setPendingLeads([]);
    }
  }, [discoveryId, searchParams]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (savingRef.current) return;
    const token = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!token) { setError("Your workspace session is not ready yet."); return; }
    if (emptySelection) { setError("No leads were selected. Return to Discover and select leads again."); return; }
    if (!name.trim() || !objective.trim()) { setError("Campaign name and description are required."); return; }
    if (!creationKey.current) {
      creationKey.current = crypto.randomUUID();
      const url = new URL(window.location.href);
      url.searchParams.set("creation_key", creationKey.current);
      window.history.replaceState(window.history.state, "", url.toString());
    }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      const created = await saveCampaign(
        token,
        name.trim(),
        objective.trim(),
        undefined,
        selectedLeads.length,
        undefined,
        undefined,
        selectedLeads,
        discoveryId || undefined,
        creationKey.current,
        workspaceId,
      );
      const campaign = created.campaign as Record<string, unknown>;
      const id = String(campaign.id || "");
      if (!created.ok || !id) throw new Error("Campaign could not be created");
      toast("success", selectedLeads.length ? "Campaign created with the selected leads." : "Campaign created — research prospects next");
      // PR-3C: new campaign must not be hidden by a cached campaigns list.
      invalidateClientCache(scopedKey(token, "campaigns", workspaceId));
      sessionStorage.removeItem(campaignLeadHandoffKey(token, discoveryId));
      router.push(`/campaigns/${id}?workspace_id=${encodeURIComponent(workspaceId)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Campaign setup failed");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16">
          <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-3">New campaign</p>
          <h1 className="text-4xl font-serif text-on-surface mb-3">Start with the outcome.</h1>
          <p className="text-base text-on-surface-variant/60 mb-10">Name the campaign and describe what this outreach should achieve. Next, add prospects and explicitly generate a strategy when you're ready.</p>
          {selectedLeads.length > 0 && <p className="text-sm text-primary mb-6">{selectedLeads.length} selected leads. They will be included when this campaign is created.</p>}
          {emptySelection && <p role="alert" className="text-sm text-error mb-6">No leads were selected. Return to Discover and select leads again.</p>}
          <form onSubmit={submit} className="space-y-6 max-w-2xl">
            <label className="block">
              <span className="text-sm font-semibold text-on-surface">Campaign name</span>
              <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Q3 Enterprise Outreach" className="mt-2 w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 outline-none focus:border-primary" />
            </label>
            <label className="block">
              <span className="text-sm font-semibold text-on-surface">Campaign description</span>
              <textarea required value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Describe the campaign and what this outreach should accomplish." rows={5} className="mt-2 w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 outline-none focus:border-primary resize-none" />
            </label>
            {error && <p className="text-sm text-error">{error}</p>}
            <div className="flex gap-3 pt-3">
              <button type="button" onClick={() => {
                const token = localStorage.getItem(ACTIVE_SESSION_KEY) || "";
                if (token && discoveryId) sessionStorage.removeItem(campaignLeadHandoffKey(token, discoveryId));
                router.push(`${searchParams.get("return") === "discovery" ? "/discovery" : "/campaigns"}?workspace_id=${encodeURIComponent(workspaceId)}`);
              }} className="rounded-lg border border-outline-variant/20 px-5 py-2.5 text-sm">Cancel</button>
              <button type="submit" disabled={saving || emptySelection} className="rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-50">{saving ? "Creating…" : "Create Campaign"}</button>
            </div>
          </form>
        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
