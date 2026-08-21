"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import NarrativeBriefing from "../briefing/NarrativeBriefing";
import { useData } from "../../lib/hooks/use-data";
import { fetchMissionControl, fetchBriefing, invalidateMissionControlCache, peekCachedMissionControl, peekCachedBriefing } from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import { useGuidedScroll } from "../../hooks/useGuidedScroll";
import { useRevealOnScroll } from "../../hooks/useRevealOnScroll";
import type { MCIntentionCard, MCHealthSummary, MCTimelineEvent, MCBriefingData } from "../../lib/domain";

const GUIDED_KEY = "loqi_guided_mission_control";

function LoadingSkeleton() {
  return (
    <div className="reading-column py-16 flex flex-col gap-16">
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

  return (
    <div className="bg-surface-lowest ambient-shadow rounded-xl p-6 border border-outline-variant/10 transition-transform hover:-translate-y-0.5 duration-200">
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
          <h4 className="text-lg font-serif text-on-surface font-normal">{card.title}</h4>
          <p className="text-sm text-on-surface-variant mt-1">{card.summary}</p>
        </div>
      </div>
      <EvidencePopover evidence={card.evidence} />
      {card.recommendedAction && (
        <div className="mt-4 pt-3 border-t border-outline-variant/10">
          <span className="text-xs text-on-surface-variant/50">Recommended: </span>
          <span className="text-sm text-primary font-medium">{card.recommendedAction}</span>
        </div>
      )}
    </div>
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
      <div className="bg-surface-lowest ambient-shadow rounded-xl p-6 border border-outline-variant/10">
        <div className="flex items-center gap-3 mb-4">
          <span className={`text-lg font-serif font-normal ${color}`}>
            {health.overallHealth.replace(/_/g, " ")}
          </span>
          <span className="text-xs text-on-surface-variant/50">
            Score: {Math.round(health.confidenceScore * 100)}%
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
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
  const categoryIcon: Record<string, string> = {
    campaign: "campaign",
    draft: "description",
    outreach: "send",
    intention: "psychiatry",
    event: "circle",
    search: "travel_explore",
    provider: "settings_cloud",
    system: "settings",
  };
  return (
    <section className="space-y-4">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
        Timeline
      </h3>
      <div className="space-y-1">
        {events.slice(0, 10).map((event) => (
          <div key={event.id} className="flex items-center gap-4 py-3 border-b border-outline-variant/10 group">
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant/30 group-hover:text-primary transition-colors">
              {categoryIcon[event.category] || "circle"}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-on-surface truncate">{event.description}</p>
              <p className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                {event.actor} &middot; {event.category}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function MissionControlDashboard() {
  const { data: mcData, loading: mcLoading, error: mcError, retry: mcRetry } = useData(fetchMissionControl, {
    initial: peekCachedMissionControl(),
  });
  const {
    data: briefingData,
    loading: briefingLoading,
    error: briefingError,
    retry: briefingRetry,
  } = useData(fetchBriefing, {
    initial: peekCachedBriefing(),
  });
  const tellLoqi = useTellLoqi("Mission Control", {
    recommendationCount: mcData?.recommendations.length ?? 0,
  });

  const pageRef = useRef<HTMLDivElement>(null);
  const prioritiesRef = useRef<HTMLDivElement>(null);
  const waitingRef = useRef<HTMLDivElement>(null);
  const healthRef = useRef<HTMLDivElement>(null);
  const guidedTimersRef = useRef<number[]>([]);
  const { scrollToSection } = useGuidedScroll(pageRef);
  useRevealOnScroll(pageRef);

  const handleBriefingDone = useCallback(() => {
    let alreadyGuided = false;
    try {
      alreadyGuided = localStorage.getItem(GUIDED_KEY) === "1";
    } catch {}
    if (alreadyGuided) return;

    const stops = [prioritiesRef, waitingRef, healthRef].filter((r) => r.current);
    stops.forEach((r, i) => {
      const timer = window.setTimeout(
        () => scrollToSection(r.current!, { duration: 1300 }),
        (i + 1) * 1800,
      );
      guidedTimersRef.current.push(timer);
    });
    try {
      localStorage.setItem(GUIDED_KEY, "1");
    } catch {}
  }, [scrollToSection]);

  useEffect(() => {
    return () => {
      guidedTimersRef.current.forEach((t) => window.clearTimeout(t));
      guidedTimersRef.current = [];
    };
  }, []);

  useEffect(() => {
    const status = mcData?.initialResearchStatus;
    if (status !== "queued" && status !== "running") return;
    const timer = window.setInterval(() => {
      invalidateMissionControlCache();
      mcRetry();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [mcData?.initialResearchStatus, mcRetry]);

  const loading = mcLoading && briefingLoading;
  const data = briefingData || mcData;
  const error = mcError || briefingError;

  if (loading && !data) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <LoadingSkeleton />
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error && !data) {
    return (
      <WorkspaceContainer>
        <AppPage>
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
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (!data) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col items-center justify-center text-center min-h-[60vh]">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
              <span className="material-symbols-outlined text-3xl">dashboard</span>
            </div>
            <p className="text-lg text-on-surface-variant/80 font-medium">Loqi is getting oriented</p>
            <p className="mt-1.5 text-sm text-on-surface-variant/50 max-w-sm leading-relaxed">
              Your first research session is starting. Loading your briefing shortly.
            </p>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  const hasBriefing = "briefing" in data && "topPriorities" in data;
  const brief = hasBriefing
    ? (data as MCBriefingData).briefing
    : { greeting: "Good morning", lines: (data as typeof mcData)?.brief?.lines ?? [], suggestion: (data as typeof mcData)?.brief?.suggestion ?? "", overallSummary: "", primaryFocus: "", topRecommendation: "" };

  const priorities = hasBriefing ? (data as MCBriefingData).topPriorities : [];
  const waiting = hasBriefing ? (data as MCBriefingData).waitingOnYou : [];
  const handled = hasBriefing ? (data as MCBriefingData).loqiHandled : [];
  const upcoming = hasBriefing ? (data as MCBriefingData).upcoming : [];
  const health = hasBriefing ? (data as MCBriefingData).workspaceHealth : null;
  const timeline = hasBriefing ? (data as MCBriefingData).timeline : [];

  // Keep the legacy Mission Control payload alongside the richer briefing;
  // it carries the research job status and result count that the briefing
  // response intentionally does not expose as lead data.
  const mc = mcData;
  const todayTasks = !hasBriefing && mc ? mc.tasks : [];
  const recommendations = !hasBriefing && mc ? mc.recommendations : [];
  const liveActivity = !hasBriefing && mc ? mc.liveActivity : [];
  const insights = !hasBriefing && mc ? mc.insights : [];
  const activeJobLabel = mc?.activeJobLabel ?? null;
  const activeJobProgress = mc?.activeJobProgress ?? null;
  const activeJobTotal = mc?.activeJobTotal ?? null;
  const initialResearchStatus = mc?.initialResearchStatus ?? null;
  const initialResearchError = mc?.initialResearchError ?? null;
  const initialResearchResultCount = mc?.initialResearchResultCount ?? null;

  const hasNewData = priorities.length > 0 || waiting.length > 0 || handled.length > 0 || upcoming.length > 0;

  return (
    <WorkspaceContainer>
      <AppPage>
        <div ref={pageRef} className="reading-column py-16 flex flex-col gap-16 pb-48">

          {/* Section 1: Today's Briefing — Narrative Layer */}
          <NarrativeBriefing
            greeting={brief.greeting || "Good morning"}
            lines={brief.lines}
            suggestion={brief.suggestion || undefined}
            onDone={handleBriefingDone}
          />

          {initialResearchStatus && (
            <section className="space-y-4">
              <div className="bg-surface-container p-6 rounded-xl border border-outline-variant/10">
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

          {/* Section 2: Top Priorities */}
          {priorities.length > 0 && (
            <section ref={prioritiesRef} className="space-y-4 reveal">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Top Priorities
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {priorities.slice(0, 4).map((card) => (
                  <IntentionCard key={card.id} card={card} />
                ))}
              </div>
            </section>
          )}

          {/* Section 3: Waiting On You (ASK_USER) */}
          {waiting.length > 0 && (
            <section ref={waitingRef} className="space-y-4 reveal">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Waiting On You
              </h3>
              <div className="space-y-3">
                {waiting.map((card) => (
                  <IntentionCard key={card.id} card={card} />
                ))}
              </div>
            </section>
          )}

          {/* Section 4: Loqi Handled (AUTO_HANDLE) */}
          {handled.length > 0 && (
            <section className="space-y-4">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Loqi Handled
              </h3>
              <div className="space-y-2">
                {handled.map((card) => (
                  <div key={card.id} className="flex items-center justify-between py-4 border-b border-outline-variant/10 group">
                    <div className="flex items-center gap-4">
                      <span className="material-symbols-outlined text-primary/30 text-lg">check_circle</span>
                      <div>
                        <span className="text-base font-serif text-on-surface">{card.title}</span>
                        <span className="text-xs text-on-surface-variant/50 block">{card.summary} · {Math.round(card.confidence * 100)}% confidence</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Section 5: Upcoming (FOLLOW_UP / NOTIFY) */}
          {upcoming.length > 0 && (
            <section className="space-y-4">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Upcoming
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {upcoming.slice(0, 4).map((card) => (
                  <IntentionCard key={card.id} card={card} />
                ))}
              </div>
            </section>
          )}

          {/* Legacy fallback sections when new briefing unavailable */}

          {/* Legacy: Today's Focus */}
          {!hasNewData && todayTasks.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Today's Focus
              </h3>
              <div className="space-y-4">
                {todayTasks.map((task) => (
                  <div key={task.id} className="flex items-center gap-4 group cursor-pointer">
                    <div className="w-5 h-5 rounded border border-outline-variant/20 flex items-center justify-center">
                      <span className="material-symbols-outlined text-[14px] opacity-0 group-hover:opacity-100 text-on-surface-variant/40">check</span>
                    </div>
                    <span className="text-lg text-on-surface">{task.title}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Workspace Health */}
          {health && (
            <div ref={healthRef}>
              <HealthSection health={health} />
            </div>
          )}

          {/* Legacy: Where I Need You */}
          {!hasNewData && recommendations.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Where I Need You
              </h3>
              <div className="space-y-6">
                {recommendations.map((rec, i) => (
                  <div key={i} className="bg-surface-lowest ambient-shadow rounded-xl p-8 border border-outline-variant/10 transition-transform hover:-translate-y-1 duration-300">
                    <div className="flex justify-between items-start mb-6">
                      <h4 className="text-2xl font-serif text-on-surface mb-2 font-normal">{rec.observation}</h4>
                      <Link href={rec.link} className="bg-primary text-on-primary text-sm px-6 py-2 rounded-full hover:opacity-90 transition-opacity font-medium">
                        {rec.action}
                      </Link>
                    </div>
                    <p className="text-base text-on-surface-variant leading-relaxed">{rec.reason}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Legacy: What I Took Care Of */}
          {!hasNewData && liveActivity.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                What I Took Care Of
              </h3>
              <div className="space-y-0">
                {liveActivity.map((item, i) => (
                  <div key={i} className="flex items-center justify-between py-6 border-b border-outline-variant/15 group">
                    <div className="flex items-center gap-6">
                      <span className="material-symbols-outlined text-primary/30 group-hover:text-primary transition-colors">
                        {item.type === "research" ? "travel_explore" : "check_circle"}
                      </span>
                      <span className="text-xl font-serif text-on-surface font-normal">{item.text}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Timeline */}
          {timeline.length > 0 && (
            <TimelineSection events={timeline} />
          )}

          {/* Legacy: Working Right Now */}
          {!hasNewData && activeJobLabel && (
            <section className="space-y-6">
              <div className="bg-surface-container p-8 rounded-xl border border-outline-variant/10">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                  <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">Working Right Now</h3>
                </div>
                <p className="text-2xl font-serif text-on-surface mb-6 font-normal">{activeJobLabel}</p>
                <div className="flex items-end justify-between mb-2">
                  <span className="text-sm text-on-surface font-medium">
                    {activeJobProgress} / {activeJobTotal} completed
                  </span>
                  <span className="text-xs text-on-surface-variant">In progress</span>
                </div>
                <div className="w-full h-1 bg-surface-container-high rounded-full overflow-hidden">
                  <div className="h-full bg-primary transition-all duration-1000 ease-in-out" style={{ width: `${(activeJobProgress ?? 0) / (activeJobTotal ?? 100) * 100}%` }} />
                </div>
              </div>
            </section>
          )}

          {/* Legacy: Intelligence */}
          {!hasNewData && insights.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">Intelligence</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {insights.map((insight, i) => (
                  <div key={i} className="bg-surface-lowest p-6 rounded-lg border border-outline-variant/10 ambient-shadow">
                    <span className="text-base text-on-surface leading-relaxed italic">&ldquo;{insight.text}&rdquo;</span>
                  </div>
                ))}
              </div>
            </section>
          )}

        </div>

        {/* Tell Loqi — sticky footer */}
        <div
          className="fixed bottom-0 z-40 bg-gradient-to-t from-background via-background/95 to-transparent pt-20 pb-6 transition-[left,right] duration-200 ease-out"
          style={{ left: "var(--sidebar-w, 16rem)", right: "var(--copilot-w, 0px)" }}
        >
          <div className="reading-column px-6">
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

      </AppPage>
    </WorkspaceContainer>
  );
}
