"use client";

import { useState } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import { useData } from "../../../lib/hooks/use-data";
import { fetchInbox } from "../../../lib/repositories";
import type { InboxDecision } from "../../../lib/domain";

function LoadingSkeleton() {
  return (
    <div className="space-y-6">
      {[1, 2].map((i) => (
        <div key={i} className="bg-surface-lowest ambient-shadow rounded-xl p-8 animate-skeleton-pulse border border-outline-variant/10">
          <div className="flex justify-between items-start mb-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-surface-high/50" />
              <div className="space-y-2">
                <div className="h-5 w-48 bg-surface-high/50 rounded-lg" />
                <div className="h-3 w-24 bg-surface-high/50 rounded-lg" />
              </div>
            </div>
            <div className="h-5 w-16 bg-surface-high/50 rounded" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
            <div className="space-y-2">
              <div className="h-3 w-20 bg-surface-high/50 rounded" />
              <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
            </div>
            <div className="space-y-2">
              <div className="h-3 w-24 bg-surface-high/50 rounded" />
              <div className="h-4 w-3/4 bg-surface-high/50 rounded-lg" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function InboxPage() {
  const { data, loading, error, retry } = useData(fetchInbox);
  const [selected, setSelected] = useState<InboxDecision | null>(null);

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <header className="animate-conversation-fade">
              <div className="h-10 w-48 bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
              <div className="h-4 w-24 bg-surface-high/50 rounded-lg animate-skeleton-pulse mt-2" />
            </header>
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

  const decisions = data?.decisions ?? [];
  const autoActions = data?.autoActions ?? [];
  const insights = data?.insights ?? [];

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Header */}
          <header className="animate-conversation-fade">
            <h1 className="text-[36px] font-serif text-on-surface mb-1 font-normal">
              Needs Your Judgment
            </h1>
            <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
              {decisions.length} Conversation{decisions.length !== 1 ? "s" : ""}
            </p>
          </header>

          {decisions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <span className="material-symbols-outlined text-3xl">inbox</span>
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No decisions need your attention</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                I will handle routine matters automatically and surface only the decisions that need your judgment.
              </p>
            </div>
          ) : (
            <>
              {/* Decision Cards */}
              <section className="space-y-6">
                {decisions.map((d, i) => (
                  <div key={d.id} className="animate-conversation-fade" style={{ animationDelay: `${i * 0.15}s` }}>
                    <div
                      onClick={() => setSelected(d)}
                      className="bg-surface-lowest ambient-shadow rounded-xl p-8 hover:-translate-y-0.5 transition-all duration-300 group cursor-pointer border border-transparent hover:border-outline-variant/20"
                    >
                      <div className="flex justify-between items-start mb-6">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center text-on-secondary-container">
                            <span className="material-symbols-outlined text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                              {d.icon}
                            </span>
                          </div>
                          <div>
                            <h3 className="text-lg font-serif text-on-surface leading-tight font-normal">{d.title}</h3>
                            <p className="text-sm text-on-surface-variant/60">{d.company}</p>
                          </div>
                        </div>
                        {d.badge === "PRIORITY" ? (
                          <span className="bg-primary text-on-primary text-[11px] uppercase tracking-wider px-2 py-1 rounded font-medium">{d.badge}</span>
                        ) : (
                          <span className="text-sm text-on-surface-variant/60">{d.badge}</span>
                        )}
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8 border-l-2 border-outline-variant/20 pl-6 ml-1">
                        <div>
                          <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-2 block">AI Summary</span>
                          <p className="text-base text-on-surface leading-relaxed">{d.summary}</p>
                        </div>
                        <div>
                          <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-2 block">Recommended Decision</span>
                          <p className="text-base font-serif italic text-primary leading-snug">{d.recommendedDecision}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-4 pt-6 border-t border-outline-variant/10">
                        <div className="flex gap-2">
                          <button onClick={(e) => { e.stopPropagation(); }} className="bg-primary text-on-primary text-sm font-medium px-6 py-2.5 rounded-full hover:opacity-90 active:scale-95 transition-all">
                            {d.actions.primary.label}
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); }} className="border border-outline-variant bg-transparent text-primary text-sm font-medium px-6 py-2.5 rounded-full hover:bg-surface-container transition-all">
                            {d.actions.secondary.label}
                          </button>
                        </div>
                        <button onClick={(e) => { e.stopPropagation(); setSelected(d); }} className="text-sm text-on-surface-variant/60 flex items-center gap-1 hover:text-primary transition-colors">
                          {d.footerLink.label}
                          <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </section>

              {/* Bottom Sections: Handled Automatically + Judgment Insights */}
              <section className="grid grid-cols-1 md:grid-cols-2 gap-12 animate-conversation-fade">
                {autoActions.length > 0 && (
                  <div>
                    <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-6 border-b border-outline-variant/10 pb-2">
                      Handled Automatically
                    </h4>
                    <div className="space-y-4">
                      {autoActions.map((item, i) => (
                        <div key={i} className="flex items-center justify-between py-2 border-t border-outline-variant/5 first:border-t-0">
                          <div className="flex items-center gap-3">
                            <span className="material-symbols-outlined text-secondary text-sm">check_circle</span>
                            <span className="text-base text-on-surface">{item.text}</span>
                          </div>
                          <span className="text-[11px] text-on-surface-variant/50">{item.time}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {insights.length > 0 && (
                  <div>
                    <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium mb-6 border-b border-outline-variant/10 pb-2">
                      Judgment Insights
                    </h4>
                    <div className="grid grid-cols-1 gap-4">
                      {insights.map((insight, i) => (
                        <div key={i} className="bg-surface-container p-4 rounded-lg flex items-start gap-3">
                          <span className="material-symbols-outlined text-primary text-[20px]">{insight.icon}</span>
                          <div>
                            <p className="text-sm font-semibold text-on-surface mb-1">{insight.title}</p>
                            <p className="text-[11px] text-on-surface-variant leading-relaxed">{insight.description}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </>
          )}

          {/* Tell Loqi */}
          <section className="pt-6 border-t border-outline-variant/20 animate-conversation-fade">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-2 px-2">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="What decisions need my attention?"
                  rows={1}
                />
                <button className="bg-primary text-on-primary w-10 h-10 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0">
                  <span className="material-symbols-outlined text-sm">arrow_upward</span>
                </button>
              </div>
            </div>
            <div className="mt-4 flex justify-center gap-3 overflow-x-auto no-scrollbar">
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                PRIORITIZE URGENT
              </button>
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                SUMMARIZE WEEKLY
              </button>
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                REVIEW DECISIONS
              </button>
            </div>
          </section>

        </div>
      </AppPage>

      {/* Decision Detail Slide-in Panel */}
      {selected && (
        <div className="fixed inset-0 z-[100]">
          <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={() => setSelected(null)} />
          <div className="absolute inset-y-0 right-0 w-full max-w-2xl bg-surface-lowest shadow-2xl flex flex-col transform transition-transform duration-500 ease-out">
            <div className="flex items-center justify-between px-8 py-6 border-b border-outline-variant/20">
              <h2 className="text-xl font-serif text-on-surface font-normal">Decision Deep-Dive</h2>
              <button onClick={() => setSelected(null)} className="w-10 h-10 flex items-center justify-center hover:bg-surface-container rounded-full">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-8 py-10 space-y-12">
              <section>
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-4">AI Summary</span>
                <div className="bg-surface-container p-6 rounded-lg">
                  <p className="text-lg font-serif italic text-primary leading-relaxed font-normal">{selected.detail.aiSummary}</p>
                </div>
              </section>
              <section>
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-4">Timeline</span>
                <div className="relative pl-6 border-l border-outline-variant/30 space-y-8">
                  {selected.detail.timeline.map((entry, i) => (
                    <div key={i} className="relative">
                      <div className={`absolute -left-[31px] top-1 w-2.5 h-2.5 rounded-full ${i === 0 ? "bg-primary" : "bg-outline-variant"}`} />
                      <p className="text-[11px] text-on-surface-variant/50 mb-1 tracking-wider">{entry.time}</p>
                      <p className="text-base text-on-surface">{entry.event}</p>
                    </div>
                  ))}
                </div>
              </section>
              <section>
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-4">Key Concerns</span>
                <ul className="space-y-3">
                  {selected.detail.concerns.map((c, i) => (
                    <li key={i} className="flex items-center gap-3 text-base">
                      <span className={`material-symbols-outlined text-[18px] ${c.type === "warning" ? "text-error" : "text-primary"}`}>
                        {c.type === "warning" ? "warning" : "info"}
                      </span>
                      {c.text}
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-4">Recommended Reply</span>
                <div className="p-6 border border-outline-variant rounded-lg bg-surface-lowest text-base text-on-surface leading-relaxed">
                  {selected.detail.recommendedReply}
                </div>
              </section>
              <section className="pb-10">
                <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium block mb-4">Original Conversation</span>
                <div className="opacity-50 hover:opacity-100 transition-opacity cursor-help border-t border-outline-variant/20 pt-4 space-y-4">
                  {selected.detail.originalConversation.map((msg, i) => (
                    <div key={i}>
                      <p className="text-sm font-bold text-on-surface mb-1">{msg.name} <span className="text-on-surface-variant/60 font-normal">({msg.role})</span></p>
                      <p className="text-sm text-on-surface">{msg.text}</p>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            <div className="p-8 border-t border-outline-variant/20 bg-surface-container flex gap-4">
              <button className="flex-1 bg-primary text-on-primary text-sm font-medium py-4 rounded-full shadow-lg active:scale-[0.98] transition-all">
                Execute Decision
              </button>
              <button className="flex-1 border border-outline-variant text-primary text-sm font-medium py-4 rounded-full active:scale-[0.98] transition-all">
                Refine Request
              </button>
            </div>
          </div>
        </div>
      )}
    </WorkspaceContainer>
  );
}
