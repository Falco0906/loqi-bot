"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import AppPage from "../../../../components/primitives/AppPage";
import { saveCampaign } from "../../../../lib/api";
import { toast } from "../../../../components/shared/Toast";
const ACTIVE_SESSION_KEY = "loqi_active_session_token";

export default function NewCampaignPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const discoveryId = searchParams?.get("discovery") || "";
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingLeads, setPendingLeads] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("loqi_pending_campaign_leads");
      if (raw) setPendingLeads(JSON.parse(raw) as Record<string, unknown>[]);
    } catch {
      setPendingLeads([]);
    }
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const token = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!token) { setError("Your workspace session is not ready yet."); return; }
    if (!name.trim() || !objective.trim()) { setError("Campaign name and objective are required."); return; }
    setSaving(true);
    setError(null);
    try {
      const created = await saveCampaign(
        token,
        name.trim(),
        objective.trim(),
        undefined,
        pendingLeads.length,
        undefined,
        undefined,
        pendingLeads,
        discoveryId || undefined,
      );
      const campaign = created.campaign as Record<string, unknown>;
      const id = String(campaign.id || "");
      if (!created.ok || !id) throw new Error("Campaign could not be created");
      toast("success", "Campaign created — research prospects next");
      sessionStorage.removeItem("loqi_pending_campaign_leads");
      router.push(`/campaigns/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Campaign setup failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16">
          <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-3">New campaign</p>
          <h1 className="text-4xl font-serif text-on-surface mb-3">Start with the outcome.</h1>
          <p className="text-base text-on-surface-variant/60 mb-10">Name the campaign and describe what this outreach should achieve. Next you'll research the exact prospects, and Loqi writes the strategy for them.</p>
          {pendingLeads.length > 0 && <p className="text-sm text-primary mb-6">{pendingLeads.length} researched leads selected. They will be included when this campaign is created.</p>}
          <form onSubmit={submit} className="space-y-6 max-w-2xl">
            <label className="block">
              <span className="text-sm font-semibold text-on-surface">Campaign name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Q3 Enterprise Outreach" className="mt-2 w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 outline-none focus:border-primary" />
            </label>
            <label className="block">
              <span className="text-sm font-semibold text-on-surface">Objective</span>
              <textarea value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="What should this campaign accomplish?" rows={5} className="mt-2 w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 outline-none focus:border-primary resize-none" />
            </label>
            {error && <p className="text-sm text-error">{error}</p>}
            <div className="flex gap-3 pt-3">
              <button type="button" onClick={() => router.push("/campaigns")} className="rounded-lg border border-outline-variant/20 px-5 py-2.5 text-sm">Cancel</button>
              <button type="submit" disabled={saving} className="rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-50">{saving ? "Creating…" : "Create Campaign"}</button>
            </div>
          </form>
        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
