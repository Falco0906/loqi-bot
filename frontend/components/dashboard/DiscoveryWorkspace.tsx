"use client";

import { useState } from "react";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import { fetchDiscovery, peekCachedDiscovery } from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import { toast } from "../shared/Toast";
import type { DiscoveryRecommendation } from "../../lib/domain";

function RecommendationCard({
  rec,
  onDismiss,
  onAction,
}: {
  rec: DiscoveryRecommendation;
  onDismiss: () => void;
  onAction: (action: string, company: string) => void;
}) {
  return (
    <article className="bg-surface-lowest ambient-shadow rounded-xl p-8 md:p-10 transition-all hover:-translate-y-0.5 duration-300 border border-outline-variant/10">
      {/* Header */}
      <div className="flex justify-between items-start mb-8">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h3 className="text-2xl font-serif text-on-surface font-normal">{rec.company}</h3>
            <span className="bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded text-[11px] uppercase tracking-wider font-medium">
              {rec.match}% Match
            </span>
          </div>
          <p className="text-xs uppercase tracking-widest text-on-surface-variant/60 font-medium">{rec.subtitle}</p>
        </div>
        <div className="flex gap-2">
          <span className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium">{rec.stage}</span>
          <span className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium">{rec.location}</span>
        </div>
      </div>

      <div className="h-px bg-outline-variant/20 mb-8" />

      {/* Body */}
      <div className="grid md:grid-cols-5 gap-8 mb-10">
        <div className="md:col-span-3">
          <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-4">Deep Reasoning</h4>
          <p className="text-base text-on-surface-variant leading-relaxed mb-6">{rec.reasoning}</p>
          <div className="space-y-4">
            <div className="flex gap-4">
              <span className="material-symbols-outlined text-primary text-lg shrink-0">check_circle</span>
              <div>
                <p className="text-sm font-semibold text-on-surface">{rec.buyingSignal}</p>
                <p className="text-sm text-on-surface-variant/70 mt-0.5">{rec.signalDetail}</p>
              </div>
            </div>
          </div>
        </div>
        <div className="md:col-span-2 space-y-6">
          <div>
            <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-4">Research Evidence</h4>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-on-surface-variant/70">Funding History</span>
                <span className="font-medium text-on-surface">{rec.funding}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-on-surface-variant/70">Hiring Trends</span>
                <span className="font-medium text-on-surface">{rec.hiring}</span>
              </div>
            </div>
          </div>

          {rec.alsoConsidered.length > 0 && (
            <div className="p-4 bg-surface-container rounded-lg">
              <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-2">Also Considered</h4>
              <ul className="space-y-2">
                {rec.alsoConsidered.map((alt) => (
                  <li key={alt.name} className="text-sm flex items-center justify-between">
                    <span className="text-on-surface">{alt.name}</span>
                    <span className={`text-[10px] italic font-medium ${alt.error ? "text-error" : "text-on-surface-variant/50"}`}>
                      {alt.note}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Action Footer */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-6 border-t border-outline-variant/20">
        <div className="flex gap-2">
          <button onClick={() => onAction("Approved", rec.company)} className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-all active:scale-[0.98]">
            Approve &amp; Research Leads
          </button>
          <button onClick={() => onAction("Added to Campaign", rec.company)} className="border border-outline-variant px-6 py-2 rounded-full text-sm font-medium hover:bg-surface-container-low transition-all">
            Add to Campaign
          </button>
        </div>
        <div className="flex gap-4">
          <button onClick={() => onAction("Saved for Later", rec.company)} className="text-sm text-on-surface-variant/60 hover:text-primary transition-colors">Review Later</button>
          <button
            onClick={() => { onAction("Ignored", rec.company); onDismiss(); }}
            className="text-sm text-error hover:opacity-80 transition-opacity"
          >
            Ignore
          </button>
        </div>
      </div>
    </article>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-16">
      {[1, 2].map((i) => (
        <div key={i} className="bg-surface-lowest rounded-xl p-8 md:p-10 border border-outline-variant/10 animate-skeleton-pulse">
          <div className="flex justify-between mb-8">
            <div className="space-y-3">
              <div className="h-6 w-48 bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-32 bg-surface-high/50 rounded-lg" />
            </div>
            <div className="flex gap-2">
              <div className="h-6 w-16 bg-surface-high/50 rounded-full" />
              <div className="h-6 w-20 bg-surface-high/50 rounded-full" />
            </div>
          </div>
          <div className="h-px bg-outline-variant/20 mb-8" />
          <div className="grid md:grid-cols-5 gap-8">
            <div className="md:col-span-3 space-y-4">
              <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-5/6 bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-4/6 bg-surface-high/50 rounded-lg" />
            </div>
            <div className="md:col-span-2 space-y-4">
              <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-3/4 bg-surface-high/50 rounded-lg" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DiscoveryWorkspace() {
  const { data, loading, error, retry } = useData(fetchDiscovery, {
    initial: peekCachedDiscovery(),
  });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const tellLoqi = useTellLoqi("Discovery", {
    recommendations: data?.recommendations.length ?? 0,
  });

  const handleCardAction = (action: string, company: string) => {
    toast("success", `${action}: ${company}`);
  };

  const visible = data?.recommendations.filter((r) => !dismissed.has(r.id)) ?? [];

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <div className="space-y-6 animate-fade-in">
              <div className="h-12 w-3/4 bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
              <div className="h-4 w-full bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
            </div>
            <LoadingSkeleton />
          </div>
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

  if (!data || data.recommendations.length === 0) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <section className="space-y-6 animate-fade-in">
              <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
                Market Discovery
              </h1>
              <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light">
                Tell me what market you want to explore and I will research companies that match your ideal customer profile.
              </p>
            </section>
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <span className="material-symbols-outlined text-3xl">explore</span>
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No recommendations yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                Describe your target market and I will surface high-conviction prospects.
              </p>
            </div>
            <section className="pt-6 border-t border-outline-variant/20">
              <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
                <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                  Tell Loqi...
                </label>
                <div className="flex items-end gap-3 px-2 pb-1">
                  <textarea
                    className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                    placeholder="Research a different market..."
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
                  onClick={() => void tellLoqi.submit("Find Series A fintech companies in cross-border payments.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  FIND SERIES A FINTECH
                </button>
                <button
                  type="button"
                  onClick={() => void tellLoqi.submit("Shift focus to healthcare SaaS companies.")}
                  className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
                >
                  SHIFT TO HEALTHCARE
                </button>
              </div>
            </section>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Section 1: Opening Narrative Briefing */}
          <section className="space-y-6 animate-fade-in">
            <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
              {data.narrativeTitle}
            </h1>
            <div className="space-y-4">
              {data.narrativeLines.map((line, i) => (
                <p key={i} className="text-lg text-on-surface-variant/60 leading-relaxed font-light">
                  {line}
                </p>
              ))}
            </div>
          </section>

          {/* Section 2: Research Toolbar & Filters */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-outline-variant/20 pb-6">
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-on-surface-variant/50 font-medium">Active Filters:</span>
              <div className="flex gap-2">
                {data.filters.map((f) => (
                  <span
                    key={f.id}
                    className="bg-surface-container px-3 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium"
                  >
                    {f.label}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex gap-4">
              <button className="flex items-center gap-1 text-sm text-on-surface-variant/60 hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-[18px]">filter_list</span>
                Industry
              </button>
              <button className="flex items-center gap-1 text-sm text-on-surface-variant/60 hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-[18px]">tune</span>
                Status
              </button>
            </div>
          </div>

          {/* Section 3: Recommended Companies Stack */}
          <div className="space-y-16">
            {visible.length === 0 && (
              <p className="text-lg text-on-surface-variant/40 italic text-center py-12">
                All recommendations reviewed. Tell me where to look next.
              </p>
            )}

            {visible.map((rec) => (
              <RecommendationCard
                key={rec.id}
                rec={rec}
                onAction={handleCardAction}
                onDismiss={() => setDismissed((prev) => new Set(prev).add(rec.id))}
              />
            ))}
          </div>

          {/* Section 4: Tell Loqi */}
          <section className="pt-6 border-t border-outline-variant/20">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="Research a different market..."
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
                onClick={() => void tellLoqi.submit("Find Series A fintech companies in cross-border payments.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                FIND SERIES A FINTECH
              </button>
              <button
                type="button"
                onClick={() => void tellLoqi.submit("Shift focus to healthcare SaaS companies.")}
                className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
              >
                SHIFT TO HEALTHCARE
              </button>
            </div>
          </section>

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
