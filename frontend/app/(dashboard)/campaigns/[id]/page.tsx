"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";
import WorkspaceContainer from "../../../../components/layout/WorkspaceContainer";
import AppPage from "../../../../components/primitives/AppPage";
import { useData } from "../../../../lib/hooks/use-data";
import { fetchCampaign } from "../../../../lib/repositories";
import { useTellLoqi } from "../../../../hooks/useTellLoqi";
import { toast } from "../../../../components/shared/Toast";
import { generateCampaignDrafts, getCampaignGenerationStatus, updateCampaign } from "../../../../lib/api";

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

export default function CampaignDetailPage() {
  const params = useParams();
  const campaignId = params.id as string;
  const router = useRouter();
  const loadCampaign = useCallback(() => fetchCampaign(campaignId), [campaignId]);
  const { data, loading, error, retry } = useData(loadCampaign);
  const tellLoqi = useTellLoqi("CampaignDetail", { campaignId });
  const token = typeof window !== "undefined" ? localStorage.getItem("loqi_active_session_token") : null;

  useEffect(() => {
    if (!data || data.status !== "generating" || !token) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await getCampaignGenerationStatus(token, campaignId);
        if (!cancelled && !status.active) window.location.reload();
      } catch {
        // Keep polling; the durable campaign state remains authoritative.
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    void poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [campaignId, data?.status, token]);

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

  const leads = data.leads || [];
  const strategy = data.strategy || {};

  async function approveStrategy() {
    if (!token) return;
    const result = await updateCampaign(token, campaignId, { status: "lead_selection" });
    if (!result.ok) return;
    if (leads.length > 0) {
      toast("success", `${leads.length} lead${leads.length === 1 ? "" : "s"} ready — generate drafts next`);
      window.location.reload();
      return;
    }
    toast("success", "Strategy approved — select leads next");
    router.push(`/discovery?campaign=${encodeURIComponent(campaignId)}`);
  }

  async function startDrafts() {
    if (!token || leads.length === 0) return;
    const result = await generateCampaignDrafts(token, campaignId);
    if (!result.ok) return;
    toast("success", "Draft generation started");
    window.location.reload();
  }

  async function launchCampaign() {
    if (!token) return;
    const result = await updateCampaign(token, campaignId, { status: "completed" });
    if (!result.ok) return;
    toast("success", "Campaign launched");
    window.location.reload();
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* 1. Narrative Briefing */}
          {data.objective && (
            <section className="animate-conversation-fade">
              <p className="text-[28px] font-serif text-on-surface leading-relaxed italic opacity-90">
                &ldquo;{data.objective}&rdquo;
              </p>
            </section>
          )}

          {/* 2. Campaign Identity */}
          <section className="animate-conversation-fade">
            <div className="flex justify-between items-end border-b border-outline-variant/20 pb-4">
              <div>
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
                  Active Campaign
                </span>
                <h3 className="text-2xl font-serif text-on-surface mt-1 font-normal">{data.name}</h3>
              </div>
              <div className="flex gap-8 text-right">
                <div>
                  <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">Status</p>
                  <p className="text-sm font-medium capitalize">{data.status.replace(/_/g, " ")}</p>
                </div>
                {data.createdAt && (
                  <div>
                    <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">Created</p>
                    <p className="text-sm font-medium">{data.createdAt}</p>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="p-6 rounded-xl border border-primary/15 bg-primary-container/5 space-y-4 animate-conversation-fade">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[11px] uppercase tracking-widest text-primary/70 font-semibold">Next step</p>
                <p className="text-lg font-serif mt-1">
                  {data.status === "strategy_review" ? "Review and approve the outreach strategy" :
                    data.status === "lead_selection" ? "Select the prospects this campaign should reach" :
                    data.status === "draft_review" ? "Review the generated drafts" :
                    data.status === "ready_to_send" ? "Launch the approved campaign" :
                    data.status === "generating" ? "Drafts are being generated" :
                    data.status === "completed" ? "Campaign complete" : "Campaign setup in progress"}
                </p>
              </div>
              {data.status === "strategy_review" && (
                <button onClick={() => void approveStrategy()} className="rounded-lg bg-success px-4 py-2.5 text-sm font-semibold text-white">Approve Strategy</button>
              )}
              {data.status === "lead_selection" && leads.length > 0 && (
                <button onClick={() => void startDrafts()} className="rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary">Generate Drafts</button>
              )}
              {data.status === "lead_selection" && leads.length === 0 && (
                <button onClick={() => router.push(`/discovery?campaign=${encodeURIComponent(campaignId)}`)} className="rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary">Select Leads</button>
              )}
              {data.status === "draft_review" && (
                <button onClick={() => router.push(`/draft?campaign=${encodeURIComponent(campaignId)}`)} className="rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary">Review Drafts</button>
              )}
            </div>
            {Object.keys(strategy).length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-on-surface-variant">
                <p><span className="font-semibold text-on-surface">Audience:</span> {String(strategy.audience || "")}</p>
                <p><span className="font-semibold text-on-surface">Channel:</span> {String(strategy.channel || "")}</p>
                <p className="md:col-span-2"><span className="font-semibold text-on-surface">Messaging angle:</span> {String(strategy.messaging_angle || "")}</p>
              </div>
            )}
            <p className="text-xs text-on-surface-variant/60">{leads.length} lead{leads.length === 1 ? "" : "s"} selected for this campaign.</p>
          </section>

          {/* 3. Narrative Journey */}
          {data.milestones.length > 0 && (
            <section className="animate-conversation-fade">
              <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-8">
                Narrative Journey
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-y-12 gap-x-8">
                {data.milestones.map((m, i) => (
                  <div key={i} className={`flex flex-col gap-2 ${m.status === "pending" ? "opacity-40" : ""}`}>
                    {m.status === "completed" ? (
                      <span className="material-symbols-outlined text-primary mb-2" style={{ fontVariationSettings: "'FILL' 1" }}>
                        check_circle
                      </span>
                    ) : m.status === "in_progress" ? (
                      <div className="w-6 h-6 rounded-full border-2 border-primary flex items-center justify-center mb-2">
                        <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                      </div>
                    ) : (
                      <span className="material-symbols-outlined text-on-surface-variant mb-2">radio_button_unchecked</span>
                    )}
                    <p className="text-sm font-bold">{m.label}</p>
                    <p className="text-[11px] text-on-surface-variant/60">{m.description}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 4. Autonomous Improvements */}
          {data.improvements.length > 0 && (
            <section className="space-y-8 animate-conversation-fade">
              <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
                Autonomous Improvements
              </h4>
              <div className="space-y-4">
                {data.improvements.map((imp, i) => (
                  <div
                    key={i}
                    className={`p-6 bg-surface-lowest border-l-2 ${i === 0 ? "border-primary" : "border-primary/20"} ambient-shadow rounded-lg`}
                  >
                    <p className="text-base text-on-surface">{imp.description}</p>
                    <div className="mt-4 flex gap-4">
                      <span className="text-[11px] text-on-surface-variant/60 uppercase italic font-medium">Reasoning:</span>
                      <span className="text-[11px] font-medium">{imp.reasoning}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 5. Timeline */}
          {data.timeline.length > 0 && (
            <section className="animate-conversation-fade">
              <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-8">
                Timeline
              </h4>
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

          {/* 6. Performance Insights */}
          {data.insights.length > 0 && (
            <section className="grid grid-cols-1 md:grid-cols-2 gap-8 animate-conversation-fade">
              {data.insights.map((insight, i) => (
                <div key={i} className="p-8 border border-outline-variant/10 rounded-xl bg-surface-lowest flex flex-col justify-center">
                  <span className="material-symbols-outlined text-primary mb-4">{insight.icon}</span>
                  <p className="text-2xl font-serif text-on-surface mb-2 font-normal">{insight.text}</p>
                  <p className="text-sm text-on-surface-variant/60 italic">{insight.footnote}</p>
                </div>
              ))}
            </section>
          )}

          {/* 7. Recommendation */}
          {data.recommendation.title && (
            <section className="animate-conversation-fade">
              <div className="p-10 bg-surface-lowest rounded-2xl border border-outline-variant/20 ambient-shadow space-y-6">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium bg-secondary-container/30 px-2 py-1 rounded">
                      Recommendation
                    </span>
                    <h5 className="text-2xl font-serif text-on-surface mt-4 font-normal">
                      {data.recommendation.title}
                    </h5>
                  </div>
                  <span className="material-symbols-outlined text-primary text-3xl">auto_awesome</span>
                </div>
                <p className="text-lg text-on-surface-variant max-w-lg leading-relaxed">
                  {data.recommendation.body}
                </p>
                <div className="flex gap-4 pt-4">
                  {data.status === "ready_to_send" && (
                    <button type="button" onClick={() => void launchCampaign()} className="bg-primary text-on-primary px-8 py-3 rounded-full text-sm font-medium hover:opacity-90 transition-all">Launch Campaign</button>
                  )}
                  {data.status === "draft_review" && (
                    <a href={`/draft?campaign=${encodeURIComponent(campaignId)}`} className="border border-outline-variant text-on-surface px-8 py-3 rounded-full text-sm font-medium hover:bg-surface-container-low transition-all">Review Drafts</a>
                  )}
                </div>
              </div>
            </section>
          )}

          {/* 8. Tell Loqi */}
          <section className="pt-6 border-t border-outline-variant/20 animate-conversation-fade">
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
