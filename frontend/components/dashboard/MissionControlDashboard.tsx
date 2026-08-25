"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import {
  fetchBriefing,
  fetchMissionControl,
  invalidateMissionControlCache,
  peekCachedBriefing,
  peekCachedMissionControl,
} from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import { useCopilot } from "../../contexts/CopilotContext";
import type { MCIntentionCard, MCHealthSummary, MCLiveActivity, MCTimelineEvent } from "../../lib/domain";

function LoadingSkeleton() {
  return (
    <div className="w-full max-w-7xl mx-auto px-6 lg:px-10 py-12 lg:py-16 flex flex-col gap-12">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-4 animate-skeleton-pulse" style={{ animationDelay: `${i * 0.1}s` }}>
          <div className="h-6 w-1/4 bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-3/4 bg-surface-high/50 rounded-lg" />
          <div className="h-20 w-full bg-surface-high/30 rounded-xl" />
        </div>
      ))}
    </div>
  );
}

function EvidencePopover({ evidence }: { evidence: MCIntentionCard["evidence"] }) {
  const [open, setOpen] = useState(false);
  if (!evidence || evidence.length === 0) return null;
  return (
    <div className="relative mt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-xs text-on-surface-variant/50 hover:text-primary transition-colors underline decoration-dotted underline-offset-2"
      >
        Why am I seeing this?
      </button>
      {open && (
        <div className="absolute top-6 left-0 z-10 bg-surface-lowest border border-outline-variant/20 rounded-lg p-4 shadow-lg min-w-[240px] space-y-2">
          {evidence.map((e, i) => (
            <div key={i} className="text-xs text-on-surface-variant space-y-0.5">
              <span className="font-medium text-on-surface">{e.reason_code.replace(/_/g, " ")}</span>
              <div className="flex gap-2">
                <span>Confidence: {Math.round(e.confidence * 100)}%</span>
                <span>Source: {e.source}</span>
              </div>
              {e.detail && <p className="italic opacity-60">{e.detail}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function IntentionCard({ card }: { card: MCIntentionCard }) {
  const priorityColor =
    card.priority === "critical" ? "text-error" :
    card.priority === "high" ? "text-warning" :
    "text-on-surface-variant";

  const isGenericTitle = new Set(["Recommend Action", "Ask User", "Auto Handle", "Follow Up", "Notify"]).has(card.title);
  const title = isGenericTitle && card.recommendedAction ? card.recommendedAction : card.title;

  return (
    <article className="bg-surface-lowest border border-outline-variant/20 rounded-lg px-5 py-5 sm:px-6 transition-colors hover:bg-surface-container-low">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[10px] uppercase tracking-wider font-semibold ${priorityColor}`}>
              {card.priority}
            </span>
            <span className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
              {Math.round(card.confidence * 100)}% confidence
            </span>
          </div>
          <h4 className="text-xl font-serif text-on-surface font-normal leading-snug">{title}</h4>
          <p className="text-base font-serif text-on-surface-variant/75 mt-1 leading-relaxed">{card.summary}</p>
        </div>
      </div>
      <EvidencePopover evidence={card.evidence} />
      {card.recommendedAction && !isGenericTitle && (
        <div className="mt-4 pt-3 border-t border-outline-variant/10 flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/45">Recommended</span>
          <span className="text-sm text-primary font-medium">{card.recommendedAction}</span>
        </div>
      )}
    </article>
  );
}

function HealthSection({ health }: { health: MCHealthSummary }) {
  const color =
    health.overallHealth === "healthy" || health.overallHealth === "good" ? "text-success" :
    health.overallHealth === "needs_attention" || health.overallHealth === "attention" ? "text-warning" :
    "text-error";

  return (
    <section className="space-y-4">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
        Workspace Health
      </h3>
      <div className="bg-surface-lowest rounded-lg p-5 border border-outline-variant/10">
        <div className="flex items-center gap-3 mb-4">
          <span className={`text-lg font-serif font-normal ${color}`}>
            {health.overallHealth.replace(/_/g, " ")}
          </span>
          <span className="text-xs text-on-surface-variant/50">
            Score: {Math.round(health.confidenceScore * 100)}%
          </span>
        </div>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 block">Velocity</span>
            <span className="text-sm font-medium text-on-surface">{health.pipelineVelocity.replace(/_/g, " ")}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 block">Ready</span>
            <span className="text-sm font-medium text-on-surface">{health.campaignsReady} campaigns</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 block">Waiting</span>
            <span className="text-sm font-medium text-on-surface">{health.campaignsWaiting} campaigns</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 block">Backlog</span>
            <span className="text-sm font-medium text-on-surface">{health.draftBacklog} drafts</span>
          </div>
        </div>
        {health.bottlenecks.length > 0 && (
          <div className="border-t border-outline-variant/10 pt-3 mt-2">
            <span className="text-xs text-on-surface-variant/50 block mb-1">Bottlenecks:</span>
            {health.bottlenecks.map((b, i) => (
              <span key={i} className="inline-block text-xs bg-surface-high/30 rounded-full px-3 py-1 mr-2 mb-1 text-on-surface-variant">
                {b}
              </span>
            ))}
          </div>
        )}
        {health.providerHealth.length > 0 && (
          <div className="border-t border-outline-variant/10 pt-3 mt-2">
            <span className="text-xs text-on-surface-variant/50 block mb-1">Providers:</span>
            {health.providerHealth.map((p, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 text-xs bg-surface-high/30 rounded-full px-3 py-1 mr-2 mb-1 text-on-surface-variant">
                <span className={`w-1.5 h-1.5 rounded-full ${String(p.status) === "healthy" ? "bg-success" : "bg-warning"}`} />
                {String(p.provider || p.provider_type || "Unknown")}
              </span>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function TimelineSection({ events }: { events: MCTimelineEvent[] }) {
  if (events.length === 0) return null;
  return (
    <section className="space-y-4 pt-2 border-t border-outline-variant/10">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
        Timeline
      </h3>
      <div className="relative ml-1 border-l border-outline-variant/10 space-y-0">
        {events.slice(0, 10).map((event) => (
          <div key={event.id} className="relative pl-4 pb-4 last:pb-0">
            <span className="absolute -left-[3px] top-1.5 w-1.5 h-1.5 rounded-full bg-outline-variant/60" />
            <div className="min-w-0">
              <p className="text-sm text-on-surface-variant/80 leading-relaxed">{event.description}</p>
              <p className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider mt-1">
                {event.actor} &middot; {event.category}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function HandledSection({ cards }: { cards: MCIntentionCard[] }) {
  if (cards.length === 0) return null;
  return (
    <section className="bg-surface-lowest border border-outline-variant/10 rounded-lg p-5 sm:p-6">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant/60 font-medium mb-5">
        Loqi Handled
      </h3>
      <ul className="space-y-4">
        {cards.map((card) => (
          <li key={card.id} className="flex items-start gap-3">
            <span className="material-symbols-outlined text-[18px] leading-6 text-primary/55">check</span>
            <div className="min-w-0">
              <p className="font-serif text-base text-on-surface">{card.title}</p>
              <p className="text-xs text-on-surface-variant/55 mt-0.5">{card.summary}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function WhatChangedSection({ activity }: { activity: MCLiveActivity[] }) {
  if (activity.length === 0) return null;
  return (
    <section className="bg-surface-lowest border border-outline-variant/10 rounded-lg p-5 sm:p-6">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant/60 font-medium mb-5">
        What Changed
      </h3>
      <ul className="space-y-0">
        {activity.slice(0, 4).map((item, index) => (
          <li key={`${item.timestamp}-${item.text}-${index}`} className="py-3 first:pt-0 last:pb-0 border-b last:border-b-0 border-outline-variant/10">
            <p className="font-serif text-base text-on-surface">{item.text}</p>
            {item.timestamp && <p className="text-[10px] uppercase tracking-wider text-on-surface-variant/45 mt-1">{item.timestamp}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function MissionControlDashboard() {
  const { open: copilotOpen } = useCopilot();
  const cachedMissionControl = peekCachedMissionControl();
  const cachedBriefing = peekCachedBriefing();
  const { data: mcData, loading: mcLoading, error: mcError, retry: mcRetry } = useData(fetchMissionControl, {
    ...(cachedMissionControl ? { initial: cachedMissionControl } : {}),
  });
  const {
    data: briefingData,
    loading: briefingLoading,
    error: briefingError,
    retry: briefingRetry,
  } = useData(fetchBriefing, {
    ...(cachedBriefing ? { initial: cachedBriefing } : {}),
  });
  const tellLoqi = useTellLoqi("Mission Control", {
    recommendationCount: mcData?.recommendations.length ?? 0,
  });

  useEffect(() => {
    const status = mcData?.initialResearchStatus;
    if (status !== "queued" && status !== "running") return;
    // PR-P1.4: in-flight guard — a slow mission-control fetch must never
    // stack overlapping requests; each tick awaits the previous one.
    let pollBusy = false;
    const timer = window.setInterval(() => {
      if (pollBusy) return;
      pollBusy = true;
      invalidateMissionControlCache();
      mcRetry().finally(() => {
        pollBusy = false;
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [mcData?.initialResearchStatus, mcRetry]);

  // The structured briefing is the final Mission Control surface. Do not
  // expose the summary-layout fallback while that authoritative request is
  // still pending, even when the summary payload was served from cache.
  const briefingPending = briefingLoading && !briefingError && !briefingData;
  const loading = (mcLoading && briefingLoading) || briefingPending;
  const data = briefingData || mcData;
  const error = mcError || briefingError;

  if (briefingPending || (loading && !data)) {
    return (
      <WorkspaceContainer>
        <LoadingSkeleton />
      </WorkspaceContainer>
    );
  }

  // The briefing is the required Mission Control surface. A cached summary
  // must not replace it when its authoritative request failed.
  if ((briefingError && !briefingData) || (error && !data)) {
    return (
      <WorkspaceContainer>
        <div className="reading-column py-16 text-center">
          <p className="text-lg text-error mb-4">{error}</p>
          <button
            onClick={() => {
              mcRetry();
              briefingRetry();
            }}
            className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Retry
          </button>
        </div>
      </WorkspaceContainer>
    );
  }

  if (!data) {
    return (
      <WorkspaceContainer>
        <div className="reading-column py-16 flex flex-col items-center justify-center text-center min-h-[60vh]">
          <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
            <span className="material-symbols-outlined text-3xl">dashboard</span>
          </div>
          <p className="text-lg text-on-surface-variant/80 font-medium">Mission Control is unavailable</p>
          <p className="mt-1.5 text-sm text-on-surface-variant/50 max-w-sm leading-relaxed">Try again to load your workspace data.</p>
        </div>
      </WorkspaceContainer>
    );
  }

  // NarrativeBriefing remains intentionally disabled. Its structured briefing
  // data is still the authoritative source for the current Mission Control UI.
  const briefing = briefingData?.briefing ?? null;
  const priorities: MCIntentionCard[] = briefingData?.topPriorities ?? [];
  const waiting: MCIntentionCard[] = briefingData?.waitingOnYou ?? [];
  const handled: MCIntentionCard[] = briefingData?.loqiHandled ?? [];
  const upcoming: MCIntentionCard[] = briefingData?.upcoming ?? [];
  const health: MCHealthSummary | null = briefingData?.workspaceHealth ?? null;
  const timeline: MCTimelineEvent[] = briefingData?.timeline ?? [];

  // The summary payload carries the research job status and result count used
  // by Mission Control without requiring a second briefing request.
  const mc = mcData;
  const liveActivity = mc?.liveActivity ?? [];
  const activeJobLabel = mc?.activeJobLabel ?? null;
  const activeJobProgress = mc?.activeJobProgress ?? null;
  const initialResearchStatus = mc?.initialResearchStatus ?? null;
  const initialResearchError = mc?.initialResearchError ?? null;
  const initialResearchResultCount = mc?.initialResearchResultCount ?? null;

  const attentionCards = [
    ...priorities,
    ...waiting.filter((card) => !priorities.some((priority) => priority.id === card.id)),
  ];
  const briefingIntroduction = briefing
    ? briefing.overallSummary || briefing.lines.join(" ")
    : "";

  return (
    <WorkspaceContainer>
      <div className="w-full max-w-7xl mx-auto py-12 lg:py-16 px-6 lg:px-10">

          {/* The briefing content is rendered in one stable pass.  The former
              NarrativeBriefing component remains disabled because it owns the
              staged/progressive animation, not this authoritative content. */}
          {briefing && (
            <header className="max-w-3xl mb-12 lg:mb-16">
              <h1 className="text-4xl md:text-5xl lg:text-[3.75rem] font-serif text-on-surface leading-[1.04] tracking-tight font-normal">
                {briefing.greeting || "Good morning"}
              </h1>
              {briefingIntroduction && (
                <p className="mt-5 text-lg md:text-xl font-serif text-on-surface-variant/75 leading-relaxed">
                  {briefingIntroduction}
                </p>
              )}
              {briefing.suggestion && (
                <p className="text-sm text-primary/85 font-medium mt-4">
                  {briefing.suggestion}
                </p>
              )}
            </header>
          )}

          {initialResearchStatus && (
            <section className="max-w-3xl space-y-4 mb-10 lg:mb-12">
              <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/10">
                <div className="flex items-center gap-3 mb-3">
                  <div className={`w-2 h-2 rounded-full ${initialResearchStatus === "failed" ? "bg-error" : initialResearchStatus === "completed" ? "bg-success" : "bg-primary animate-pulse"}`} />
                  <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">Initial research</h3>
                </div>
                {initialResearchStatus === "failed" ? (
                  <p className="text-sm text-error">Research could not be completed{initialResearchError ? `: ${initialResearchError}` : "."}</p>
                ) : initialResearchStatus === "completed" ? (
                  <>
                    <p className="text-sm text-on-surface">
                      {initialResearchResultCount !== null
                        ? `I found ${initialResearchResultCount} compan${initialResearchResultCount === 1 ? "y" : "ies"} matching your ICP. Your results are ready to review in Discovery.`
                        : "Your first prospect research is complete. Results are ready to review in Discovery."}
                    </p>
                    <Link
                      href="/discovery"
                      className="inline-flex mt-4 bg-primary text-on-primary px-5 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
                    >
                      Review Leads
                    </Link>
                  </>
                ) : (
                  <>
                    <p className="text-lg font-serif text-on-surface mb-4">{activeJobLabel || "Preparing your prospect research"}</p>
                    <div className="w-full h-1 bg-surface-container-high rounded-full overflow-hidden">
                      <div className="h-full bg-primary transition-all duration-500" style={{ width: `${activeJobProgress ?? 0}%` }} />
                    </div>
                  </>
                )}
              </div>
            </section>
          )}

          <div className={copilotOpen ? "flex flex-col gap-10 lg:gap-12" : "grid grid-cols-1 xl:grid-cols-12 gap-10 xl:gap-8 2xl:gap-12"}>
            <main className={copilotOpen ? "space-y-10 lg:space-y-12 min-w-0" : "xl:col-span-8 space-y-10 lg:space-y-12 min-w-0"}>
              {attentionCards.length > 0 && (
                <section className="space-y-5">
                  <div className="flex items-end justify-between gap-4">
                    <h2 className="font-serif text-3xl md:text-4xl text-on-surface leading-tight font-normal">Needs your attention</h2>
                    <span className="material-symbols-outlined text-error/80 text-[22px] mb-1">warning</span>
                  </div>
                  <div className="space-y-3">
                    {attentionCards.slice(0, 4).map((card) => (
                      <IntentionCard key={card.id} card={card} />
                    ))}
                  </div>
                </section>
              )}

              {(handled.length > 0 || liveActivity.length > 0) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 lg:gap-6">
                  <HandledSection cards={handled} />
                  <WhatChangedSection activity={liveActivity} />
                </div>
              )}
            </main>

            <aside className={copilotOpen ? "space-y-8 lg:space-y-10 min-w-0" : "xl:col-span-4 xl:pt-16 space-y-8 lg:space-y-10 min-w-0"}>
              {upcoming.length > 0 && (
                <section className="bg-surface-lowest border border-outline-variant/10 rounded-lg p-5 sm:p-6">
                  <h3 className="text-xs uppercase tracking-widest text-on-surface-variant/60 font-medium mb-5">Upcoming</h3>
                  <div className="space-y-4">
                    {upcoming.slice(0, 4).map((card) => (
                      <div key={card.id} className="border-b border-outline-variant/10 pb-4 last:border-b-0 last:pb-0">
                        <p className="font-serif text-base text-on-surface">{card.title}</p>
                        <p className="text-sm text-on-surface-variant/65 mt-1 leading-relaxed">{card.summary}</p>
                        <EvidencePopover evidence={card.evidence} />
                      </div>
                    ))}
                  </div>
                </section>
              )}
              {health && <HealthSection health={health} />}
              {timeline.length > 0 && <TimelineSection events={timeline} />}
            </aside>
          </div>

        </div>

      {/* Tell Loqi remains the final Mission Control action, in normal document
          flow so it cannot reserve an empty viewport or cover briefing data. */}
      <div className="w-full mt-12 lg:mt-16 pb-8">
          <div className="w-full max-w-7xl mx-auto px-6 lg:px-10">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow focus-within:ring-2 focus-within:ring-primary/5 transition-all">
              <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="What would you like me to work on next?"
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
                onClick={() => void tellLoqi.submit("Reprioritize my list based on what matters most right now.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                REPRIORITIZE LIST
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Draft a weekly summary of workspace progress and priorities.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                DRAFT WEEKLY SUMMARY
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Find new venture leads that match my ICP.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                FIND NEW VENTURE LEADS
              </button>
            </div>
          </div>
      </div>
    </WorkspaceContainer>
  );
}
