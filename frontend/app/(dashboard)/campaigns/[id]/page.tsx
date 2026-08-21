"use client";

import { useParams, useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import AppPage from "../../../../components/primitives/AppPage";
import { useData } from "../../../../lib/hooks/use-data";
import { fetchCampaign, invalidateMissionControlCache } from "../../../../lib/repositories";
import type { CampaignData, CampaignLaunchProgress } from "../../../../lib/domain";
import { useTellLoqi } from "../../../../hooks/useTellLoqi";
import { useActionHandlers } from "../../../../hooks/useActionHandlers";
import { toast } from "../../../../components/shared/Toast";
import {
  deleteCampaign,
  duplicateCampaign,
  generateCampaignDrafts,
  generateCampaignStrategy,
  getStrategyGenerationStatus,
  getCampaignGenerationStatus,
  updateCampaign,
} from "../../../../lib/api";
import CampaignStatusBadge from "../../../../components/campaigns/CampaignStatusBadge";
import StrategyDocument from "../../../../components/campaigns/StrategyDocument";
import CampaignStrategyGate from "../../../../components/campaigns/CampaignStrategyGate";
import CampaignProgressStepper from "../../../../components/campaigns/CampaignProgressStepper";
import CampaignLeadsSection from "../../../../components/campaigns/CampaignLeadsSection";
import CampaignDraftsSection from "../../../../components/campaigns/CampaignDraftsSection";
import CampaignNarrative from "../../../../components/campaigns/CampaignNarrative";
import ExecutionWorkspace from "../../../../components/campaigns/ExecutionWorkspace";
import { buildResearchUrl } from "../../../../lib/discovery-mode";
import Icon from "../../../../components/shared/Icon";

function researchUrlForCampaign(data: CampaignData | null): string {
  if (!data?.id) return "/discovery";
  const strategy = data.strategy ?? {};
  return buildResearchUrl({
    campaignId: data.id,
    campaignName: data.name,
    objective: data.objective,
    audience: String(strategy.audience || ""),
    messagingAngle: String(strategy.messaging_angle || ""),
  });
}

function LoadingSkeleton() {
  return (
    <div className="reading-column py-16 flex flex-col gap-16">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="space-y-4 animate-skeleton-pulse" style={{ animationDelay: `${i * 0.1}s` }}>
          <div className="h-5 w-3/4 bg-surface-high/50 rounded-lg" />
          <div className="h-3 w-1/2 bg-surface-high/50 rounded-lg" />
          <div className="h-3 w-2/3 bg-surface-high/50 rounded-lg" />
        </div>
      ))}
    </div>
  );
}

function SectionLabel({ icon, children }: { icon: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
      <span className="material-symbols-outlined text-[13px]" style={{ fontVariationSettings: "'FILL' 1" }}>
        {icon}
      </span>
      {children}
    </span>
  );
}

export default function CampaignDetailPage() {
  const params = useParams();
  const campaignId = params.id as string;
  const router = useRouter();
  const loadCampaign = useCallback(() => fetchCampaign(campaignId), [campaignId]);
  const { data, loading, error, retry, mutate } = useData(loadCampaign);

  /**
   * Refetch the campaign and patch it in place. Used after every mutation —
   * never `window.location.reload()`, so the sidebar stays mounted, scroll is
   * preserved and only the changed sections re-render.
   */
  const refreshCampaign = useCallback(async () => {
    const fresh = await loadCampaign();
    if (fresh) mutate(fresh);
    return fresh;
  }, [loadCampaign, mutate]);
  const tellLoqi = useTellLoqi("CampaignDetail", { campaignId });
  const token = typeof window !== "undefined" ? localStorage.getItem("loqi_active_session_token") : null;
  const [strategyBusy, setStrategyBusy] = useState(false);
  // PR-P1.4: generateStrategy's poll loop must not keep running (and keep
  // hitting the API) once the user has navigated away from this page.
  const strategyPollAborted = useRef(false);
  useEffect(() => {
    strategyPollAborted.current = false;
    return () => { strategyPollAborted.current = true; };
  }, []);
  const [launchStarted, setLaunchStarted] = useState(false);
  const [liveLaunch, setLiveLaunch] = useState<CampaignLaunchProgress | null>(null);
  const [executionDismissed, setExecutionDismissed] = useState(false);

  useActionHandlers({
    generate_strategy: () => { void generateStrategy(); },
    add_leads: () => { router.push(researchUrlForCampaign(data)); },
    attach_discovery: () => { router.push(researchUrlForCampaign(data)); },
    open_campaign: () => { /* already here */ },
    duplicate_campaign: () => { void duplicateCampaignAction(); },
    delete_campaign: () => { void deleteCampaignAction(); },
  });

  useEffect(() => {
    if (!data || data.generation?.status !== "processing" || !token) return;
    let cancelled = false;
    // PR-P1.4: in-flight guard — generation-status polls must not overlap
    // when a request outlives the 2s interval.
    let pollBusy = false;
    const poll = async () => {
      if (cancelled || pollBusy) return;
      pollBusy = true;
      try {
        const status = await getCampaignGenerationStatus(token, campaignId);
        if (!cancelled && !status.active) void refreshCampaign();
      } catch {
        // Keep polling; the durable campaign state remains authoritative.
      } finally {
        pollBusy = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    void poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [campaignId, data?.generation?.status, token]);

  /**
   * Campaigns built from a Discovery carry their strategy automatically —
   * the backend enqueues generation when research is attached. Poll quietly
   * until the carried strategy lands so the page shows it without the user
   * clicking Generate. Bounded; stops on first appearance.
   */
  const waitingForCarriedStrategy = Boolean(
    data && !(Object.keys(data.strategy || {}).length > 0) && (data.leads?.length ?? 0) > 0 && data.discoveryId,
  );
  useEffect(() => {
    if (!waitingForCarriedStrategy || !token) return;
    let cancelled = false;
    // PR-P1.4: in-flight guard for the carried-strategy poll.
    let pollBusy = false;
    const budgetMs = 90_000;
    const deadline = Date.now() + budgetMs;
    let timer: number | undefined;
    const poll = async () => {
      if (cancelled || pollBusy) return;
      if (Date.now() > deadline) {
        if (timer !== undefined) window.clearInterval(timer);
        return;
      }
      pollBusy = true;
      try {
        const fresh = await loadCampaign().catch(() => null);
        if (cancelled) return;
        if (fresh && Object.keys(fresh.strategy || {}).length > 0) {
          mutate(fresh);
          if (timer !== undefined) window.clearInterval(timer);
          return;
        }
      } finally {
        pollBusy = false;
      }
    };
    void poll();
    timer = window.setInterval(() => void poll(), 3000);
    return () => { cancelled = true; if (timer !== undefined) window.clearInterval(timer); };
  }, [waitingForCarriedStrategy, loadCampaign, mutate, token]);

  const leads = useMemo(() => data?.leads || [], [data?.leads]);
  const strategy = useMemo(() => data?.strategy || {}, [data?.strategy]);
  const audience = useMemo(() => String(strategy.audience || ""), [strategy]);
  const messagingAngle = useMemo(() => String(strategy.messaging_angle || ""), [strategy]);
  const step = data?.currentStep || "";
  const generating = data?.generation?.status === "processing";

  async function generateStrategy(force = false) {
    if (!token) return;
    setStrategyBusy(true);
    try {
      const started = await generateCampaignStrategy(token, campaignId, force);
      if (!started.ok) return;
      if (started.reused || !started.job_id) {
        if (started.reused) toast("success", "Strategy already covers this objective");
        await refreshCampaign();
        return;
      }
      toast("success", "Strategy generation started");
      let attempts = 0;
      while (attempts < 120) {
        if (strategyPollAborted.current) return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
        attempts += 1;
        if (strategyPollAborted.current) return;
        const status = await getStrategyGenerationStatus(token, campaignId, started.job_id);
        if (strategyPollAborted.current) return;
        if (status.status === "completed") {
          toast("success", "Strategy generated");
          await refreshCampaign();
          return;
        }
        if (status.status === "failed") {
          toast("error", `Strategy generation failed: ${status.error || "unknown error"}`);
          return;
        }
      }
      toast("error", "Strategy generation timed out — try again");
    } catch {
      toast("error", "Strategy generation failed");
    } finally {
      setStrategyBusy(false);
    }
  }

  async function startDrafts() {
    if (!token || leads.length === 0) return;
    try {
      const result = await generateCampaignDrafts(token, campaignId);
      if (!result.ok) return;
      toast("success", "Draft generation started");
      await refreshCampaign();
    } catch {
      // The start call may have aborted client-side (timeout/network) even
      // though the backend accepted the batch. Reconnect through the durable
      // generation state: if a batch is running or finished, resume polling
      // instead of surfacing a false failure.
      try {
        const status = await getCampaignGenerationStatus(token, campaignId);
        if (status.ok && (status.active || status.status === "processing" || status.status === "completed")) {
          toast("success", "Draft generation already running");
          await refreshCampaign();
          return;
        }
      } catch {
        /* fall through to the error toast */
      }
      toast("error", "Could not start draft generation — try again");
    }
  }

  async function launchCampaign() {
    if (!token) return;
    try {
      const result = await updateCampaign(token, campaignId, { status: "completed" });
      if (!result.ok) return;
      setLaunchStarted(true);
      setExecutionDismissed(false);
      setLiveLaunch({ status: "sending", total: 0, sent: 0, failed: 0 });
      toast("success", "Campaign launched — sending outreach");
    } catch (err) {
      const detail =
        err instanceof Error
          ? (() => {
              try {
                return JSON.parse(err.message)?.detail || err.message;
              } catch {
                return err.message;
              }
            })()
          : "Launch failed";
      toast("error", String(detail));
    }
  }

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <LoadingSkeleton />
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 text-center">
            <p className="text-lg text-error mb-4">{error}</p>
            <button
              onClick={retry}
              className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Retry
            </button>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (!data) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 text-center">
            <p className="text-lg text-on-surface-variant/60">Campaign not found</p>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  const hasStrategy = Object.keys(strategy).length > 0;
  const pendingDrafts = Number(data.pendingDrafts || 0);
  const approvedDrafts = Number(data.approvedDrafts || 0);

  const launch = liveLaunch ?? data.launch;
  const launchStatus = launch?.status || "";
  const launchActive =
    !executionDismissed &&
    (launchStarted ||
      (["sending", "launched", "failed", "partial"].includes(launchStatus) &&
        (launch?.total ?? 0) > 0));
  const launching = launchStatus === "sending";
  const launchTerminal = ["launched", "failed", "partial"].includes(launchStatus);
  const sentDrafts = launch?.sent ?? 0;
  const launchFailed = launch?.failed ?? 0;
  const narrativeStatus = launching ? data.status : launchTerminal ? "completed" : data.status;

  async function renameCampaignAction() {
    if (!token) return;
    const newName = window.prompt("Rename campaign", data?.name || "");
    if (!newName || newName.trim() === data?.name || !newName.trim()) return;
    try {
      const res = await updateCampaign(token, campaignId, { name: newName.trim() });
      if (!res.ok) return;
      toast("success", "Campaign renamed");
      await refreshCampaign();
    } catch { toast("error", "Failed to rename campaign"); }
  }

  async function archiveCampaignAction() {
    if (!token) return;
    try {
      const res = await updateCampaign(token, campaignId, { status: "archived" });
      if (!res.ok) return;
      toast("success", "Campaign archived");
      await refreshCampaign();
    } catch { toast("error", "Failed to archive campaign"); }
  }

  async function restoreCampaignAction() {
    if (!token) return;
    try {
      const res = await updateCampaign(token, campaignId, { status: "planning" });
      if (!res.ok) return;
      toast("success", "Campaign restored");
      await refreshCampaign();
    } catch { toast("error", "Failed to restore campaign"); }
  }

  async function duplicateCampaignAction() {
    if (!token) return;
    try {
      const res = await duplicateCampaign(token, campaignId);
      if (!res.ok) return;
      toast("success", "Campaign duplicated");
      invalidateMissionControlCache();
      await refreshCampaign();
    } catch { toast("error", "Failed to duplicate campaign"); }
  }

  async function deleteCampaignAction() {
    if (!token) return;
    if (!window.confirm("Delete this campaign? This removes it from your workspace.")) return;
    try {
      await deleteCampaign(token, campaignId);
      toast("success", "Campaign deleted");
      invalidateMissionControlCache();
      router.push("/campaigns");
    } catch { toast("error", "Failed to delete campaign"); }
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-10 flex flex-col gap-12">

          {/* ─── Campaign Header ─── */}
          <section className="animate-conversation-fade">
            <button
              onClick={() => router.push("/campaigns")}
              className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant/60 hover:text-primary transition-colors mb-4"
            >
              <Icon name="chevron_right" className="text-sm rotate-180" />
              All campaigns
            </button>
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-outline-variant/20 pb-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl font-serif text-on-surface font-normal truncate">{data.name}</h1>
                  <CampaignStatusBadge status={data.status} />
                </div>
                {data.objective ? (
                  <p className="mt-2 text-sm text-on-surface-variant/70 italic leading-relaxed max-w-xl">
                    &ldquo;{data.objective}&rdquo;
                  </p>
                ) : null}
                {data.createdAt ? (
                  <p className="mt-1.5 text-xs text-on-surface-variant/50">
                    Created {data.createdAt}
                  </p>
                ) : null}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => void renameCampaignAction()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
                >
                  <span className="material-symbols-outlined text-sm">edit</span>
                  Rename
                </button>
                {data.status === "archived" ? (
                  <button
                    onClick={() => void restoreCampaignAction()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">restore</span>
                    Restore
                  </button>
                ) : (
                  <button
                    onClick={() => void archiveCampaignAction()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">archive</span>
                    Archive
                  </button>
                )}
                <button
                  onClick={() => void duplicateCampaignAction()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
                >
                  <span className="material-symbols-outlined text-sm">copy_all</span>
                  Duplicate
                </button>
                <button
                  onClick={() => void deleteCampaignAction()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-error/50 hover:text-error transition-all"
                >
                  <span className="material-symbols-outlined text-sm">delete</span>
                  Delete
                </button>
              </div>
            </div>
          </section>

          {/* ─── Execution Workspace (live during and after launch) ─── */}
          {launchActive && (
            <section className="animate-conversation-fade">
              <ExecutionWorkspace
                token={token}
                campaignId={campaignId}
                campaignName={data.name}
                initial={launch}
                launched={launchStarted}
                onProgress={setLiveLaunch}
                onTerminal={() => invalidateMissionControlCache()}
                onCollapse={() => setExecutionDismissed(true)}
              />
            </section>
          )}

          {/* ─── Strategy (hero) — gate until it exists; the workspace only reveals after generation ─── */}
          <section className="animate-conversation-fade">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <SectionLabel icon="auto_awesome">Strategy</SectionLabel>
              {hasStrategy && !strategyBusy && (
                <button
                  onClick={() => void generateStrategy(true)}
                  className="rounded-lg border border-outline-variant/30 px-3 py-1.5 text-xs font-semibold text-on-surface-variant/70 hover:border-primary/50 hover:text-primary transition-all"
                >
                  Regenerate
                </button>
              )}
            </div>
            {hasStrategy ? (
              <StrategyDocument
                objective={data.objective}
                strategy={strategy}
                generating={strategyBusy}
              />
            ) : (
              <CampaignStrategyGate
                leadsCount={leads.length}
                strategyBusy={strategyBusy}
                researchUrl={researchUrlForCampaign(data)}
                onGenerateStrategy={() => void generateStrategy()}
              />
            )}
          </section>

          {/* ─── Workflow progress (informational) ─── */}
          <section className="animate-conversation-fade">
            <div className="mb-3">
              <SectionLabel icon="route">Progress</SectionLabel>
            </div>
            <CampaignProgressStepper step={step} />
          </section>

          {/* ─── Leads ─── */}
          <section className="animate-conversation-fade">
            <CampaignLeadsSection
              token={token}
              campaignId={campaignId}
              campaignName={data.name}
              leads={leads}
              objective={data.objective}
              audience={audience}
              messagingAngle={messagingAngle}
              onLeadsChanged={() => void refreshCampaign()}
            />
          </section>

          {/* ─── Drafts (appear when they exist — nothing disappears) ─── */}
          <section className="animate-conversation-fade">
            <CampaignDraftsSection
              token={token}
              campaignId={campaignId}
              generating={generating}
              step={step}
              locked={launching}
            />
          </section>

          {/* ─── Activity Timeline ─── */}
          {data.timeline.length > 0 && (
            <section className="animate-conversation-fade">
              <div className="mb-4">
                <SectionLabel icon="history">Activity Timeline</SectionLabel>
              </div>
              <div className="space-y-8 relative">
                <div className="absolute left-[7px] top-2 bottom-0 w-px bg-outline-variant/30" />
                {data.timeline.map((entry, i) => (
                  <div key={i} className="relative pl-8">
                    <div className={`absolute left-0 top-[6px] w-4 h-4 rounded-full ${i === 0 ? "bg-primary" : "bg-outline-variant"} ring-4 ring-surface`} />
                    <p className="text-sm font-bold mb-1">{entry.date}</p>
                    <ul className="space-y-1">
                      {entry.events.map((evt, j) => (
                        <li key={j} className="text-base text-on-surface-variant flex items-center gap-2">
                          <span className="w-1 h-1 bg-outline rounded-full shrink-0" />
                          {evt}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ─── Narrative AI — contextual, one next action ─── */}
          <section className="animate-conversation-fade">
            <CampaignNarrative
              campaignId={campaignId}
              campaignName={data.name}
              objective={data.objective}
              audience={audience}
              messagingAngle={messagingAngle}
              status={narrativeStatus}
              step={step}
              leadCount={leads.length}
              pendingDrafts={pendingDrafts}
              approvedDrafts={approvedDrafts}
              sentDrafts={sentDrafts}
              launchTotal={launch?.total ?? 0}
              launchFailed={launchFailed}
              launching={launching}
              hasStrategy={hasStrategy}
              generating={generating}
              onGenerateStrategy={() => void generateStrategy()}
              onGenerateDrafts={() => void startDrafts()}
              onLaunch={() => void launchCampaign()}
            />
          </section>

          {/* ─── Tell Loqi ─── */}
          <section className="pt-4 border-t border-outline-variant/20 animate-conversation-fade">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2 px-2">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="What would you like me to adjust in this campaign?"
                  rows={1}
                  value={tellLoqi.text}
                  onChange={(e) => tellLoqi.setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void tellLoqi.submit();
                    }
                  }}
                />
                <button
                  type="button"
                  disabled={tellLoqi.sending || !tellLoqi.text.trim()}
                  onClick={() => void tellLoqi.submit()}
                  className="bg-primary text-on-primary w-10 h-10 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0 disabled:opacity-40"
                >
                  <span className="material-symbols-outlined text-sm">arrow_upward</span>
                </button>
              </div>
            </div>
            <div className="mt-4 flex justify-center gap-3 overflow-x-auto no-scrollbar">
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Pause this campaign temporarily.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                PAUSE CAMPAIGN
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Duplicate this campaign for a new market segment.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                DUPLICATE TO NEW
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Export a full performance report for this campaign.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                EXPORT REPORT
              </button>
            </div>
          </section>

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
