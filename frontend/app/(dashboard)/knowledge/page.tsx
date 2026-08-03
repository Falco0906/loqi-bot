"use client";

import { useState } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import { useData } from "../../../lib/hooks/use-data";
import { fetchKnowledge } from "../../../lib/repositories";
import { useTellLoqi } from "../../../hooks/useTellLoqi";
import type { KnowledgeCard as KnowledgeCardType } from "../../../lib/domain";
import { ProfileValue } from "../../../components/shared/ProfileValue";

function KnowledgeCard({ card, isOpen, onToggle }: { card: KnowledgeCardType; isOpen: boolean; onToggle: () => void }) {
  return (
    <div
      className={`bg-surface-lowest ambient-shadow rounded-xl overflow-hidden border border-transparent transition-all duration-200 ${
        isOpen ? "border-primary/20" : "hover:border-outline-variant/20"
      }`}
    >
      <button onClick={onToggle} className="w-full flex justify-between items-center p-6 text-left">
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.15em] text-on-surface-variant/50 font-medium mb-1">
            {card.category}
          </span>
          <h3 className="text-2xl font-serif text-on-surface font-normal">{card.title}</h3>
        </div>
        <div className="flex items-center gap-4">
          <span
            className={`text-[10px] uppercase tracking-wider font-semibold px-3 py-1 rounded-full ${
              card.confidenceMode === "high"
                ? "bg-emerald-900/30 text-emerald-400"
                : card.confidenceMode === "medium"
                ? "bg-surface-high text-on-surface-variant"
                : card.confidenceMode === "low"
                ? "bg-error-container/20 text-error"
                : "bg-surface-high text-on-surface-variant"
            }`}
          >
            {card.confidence}
          </span>
          <span className={`material-symbols-outlined text-on-surface-variant/60 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}>
            expand_more
          </span>
        </div>
      </button>
      <div className={`overflow-hidden transition-all duration-300 ${isOpen ? "max-h-96 opacity-100" : "max-h-0 opacity-0"}`}>
        <div className="px-6 pb-8 pt-6 border-t border-outline-variant/10">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {card.fields.map((field, i) => (
              <div key={i} className={field.variant === "tags" ? "" : field.variant === "quote" ? "bg-surface-container p-4 rounded-lg" : ""}>
                <h4 className="text-[11px] uppercase tracking-wider font-semibold mb-2 text-on-surface-variant">
                  {field.label}
                </h4>
                  {field.variant === "tags" ? (
                    <div className="flex flex-wrap gap-2">
                      {field.tags?.map((tag) => (
                        <span key={tag} className="px-4 py-1.5 bg-surface-container rounded-full text-sm">{tag}</span>
                      ))}
                    </div>
                  ) : field.variant === "quote" ? (
                    <div className="text-sm text-on-surface-variant italic leading-snug">
                      <ProfileValue value={field.value} />
                    </div>
                  ) : (
                    <div className={`${card.fields.length <= 2 ? "text-2xl font-serif text-primary font-normal" : "text-sm text-on-surface"}`}>
                      <ProfileValue value={field.value} />
                    </div>
                  )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="bg-surface-lowest rounded-xl overflow-hidden border border-outline-variant/10 animate-skeleton-pulse">
          <div className="flex justify-between items-center p-6">
            <div className="space-y-2">
              <div className="h-3 w-16 bg-surface-high/50 rounded" />
              <div className="h-6 w-32 bg-surface-high/50 rounded-lg" />
            </div>
            <div className="flex items-center gap-4">
              <div className="h-5 w-24 bg-surface-high/50 rounded-full" />
              <div className="h-5 w-5 bg-surface-high/50 rounded" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function KnowledgePage() {
  const { data, loading, error, retry } = useData(fetchKnowledge);
  const [openCard, setOpenCard] = useState<string | null>(null);
  const teachLoqi = useTellLoqi("Knowledge", {
    cards: data?.cards.length ?? 0,
  });

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-16">
            <div className="space-y-4 animate-skeleton-pulse">
              <div className="h-10 w-64 bg-surface-high/50 rounded-lg" />
              <div className="h-4 w-96 bg-surface-high/50 rounded-lg" />
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
            <button onClick={retry} className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity">
              Retry
            </button>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Headline */}
          <header className="animate-conversation-fade">
            <h1 className="text-4xl md:text-5xl font-serif text-on-surface mb-4 font-normal">
              Current Understanding
            </h1>
            <p className="text-lg text-on-surface-variant/80 leading-relaxed">
              This is my current understanding of your business. Update anything that no longer reflects reality.
            </p>
          </header>

          {!data ? (
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <span className="material-symbols-outlined text-3xl">psychology</span>
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No knowledge yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                As we work together, I will build a shared understanding of your business. Share what matters and I will remember it.
              </p>
            </div>
          ) : (
            <>
              {/* Knowledge Cards */}
              <section className="space-y-4">
                {data.cards.map((card, i) => (
                  <div key={card.id} className="animate-conversation-fade" style={{ animationDelay: `${i * 0.15}s` }}>
                    <KnowledgeCard
                      card={card}
                      isOpen={openCard === card.id}
                      onToggle={() => setOpenCard(openCard === card.id ? null : card.id)}
                    />
                  </div>
                ))}
              </section>

              {/* Recent Learnings + Evolution */}
              <section className="grid grid-cols-1 md:grid-cols-2 gap-12 animate-conversation-fade">
                {data.timeline.length > 0 && (
                  <div>
                    <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-6 flex items-center gap-2">
                      <span className="material-symbols-outlined text-base">history</span>
                      Recent Learnings
                    </h3>
                    <div className="relative pl-6 space-y-8 before:content-[''] before:absolute before:left-[7px] before:top-1 before:bottom-0 before:w-px before:bg-outline-variant/20">
                      {data.timeline.map((entry, i) => (
                        <div key={i} className="relative">
                          <div className={`absolute -left-[27px] top-1.5 w-2 h-2 rounded-full ring-4 ring-surface ${entry.highlight ? "bg-primary" : "bg-outline-variant/40"}`} />
                          <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/50 font-medium block mb-1">{entry.time}</span>
                          <p className="text-sm text-on-surface leading-snug">{entry.event}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {data.evolution.length > 0 && (
                  <div>
                    <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-6 flex items-center gap-2">
                      <span className="material-symbols-outlined text-base">trending_up</span>
                      Evolution
                    </h3>
                    <div className="space-y-4">
                      {data.evolution.map((item, i) => (
                        <div key={i} className="flex items-center justify-between py-2 border-b border-outline-variant/10">
                          <span className="text-sm text-on-surface">{item.label}</span>
                          <span className="material-symbols-outlined text-secondary text-base">check_circle</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>

              {/* Footer */}
              <footer className="text-center animate-conversation-fade">
                <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/30 font-medium">
                  {data.brainVersion} &bull; {data.lastSync}
                </p>
              </footer>
            </>
          )}

          {/* Teach Loqi */}
          <section className="pt-6 border-t border-outline-variant/20 animate-conversation-fade">
            <div className="bg-surface-container-low rounded-2xl p-8 border border-outline-variant/20 shadow-inner">
              <h3 className="text-2xl font-serif text-on-surface font-normal mb-2">Teach Loqi...</h3>
              <p className="text-sm text-on-surface-variant/70 mb-6">What should I understand differently about your business today?</p>
              <div className="relative mb-6">
                <textarea
                  className="w-full bg-surface-lowest border-0 border-b border-outline-variant/20 focus:border-primary focus:ring-0 text-sm p-4 min-h-[120px] transition-all resize-none placeholder:text-on-surface-variant/30 outline-none rounded-lg"
                  placeholder="What should I understand differently?"
                  value={teachLoqi.text}
                  onChange={(e) => teachLoqi.setText(e.target.value)}
                />
                <button
                  type="button"
                  disabled={teachLoqi.sending || !teachLoqi.text.trim()}
                  onClick={() => void teachLoqi.submit()}
                  className="absolute bottom-4 right-4 bg-primary text-on-primary px-6 py-2 rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-2 hover:opacity-90 transition-opacity disabled:opacity-40"
                >
                  Update Brain
                  <span className="material-symbols-outlined text-sm">send</span>
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-medium">Try saying:</span>
                <button
                  type="button"
                  onClick={() => void teachLoqi.submit("Our pricing has changed — we now charge per seat.")}
                  className="px-4 py-1.5 border border-outline-variant/20 rounded-full text-xs text-on-surface-variant/70 hover:bg-surface-container transition-colors"
                >
                  &ldquo;Our pricing has changed&rdquo;
                </button>
                <button
                  type="button"
                  onClick={() => void teachLoqi.submit("Ignore agencies — focus only on direct enterprise customers.")}
                  className="px-4 py-1.5 border border-outline-variant/20 rounded-full text-xs text-on-surface-variant/70 hover:bg-surface-container transition-colors"
                >
                  &ldquo;Ignore agencies&rdquo;
                </button>
                <button
                  type="button"
                  onClick={() => void teachLoqi.submit("Prioritize outreach to CTOs at Series A companies.")}
                  className="px-4 py-1.5 border border-outline-variant/20 rounded-full text-xs text-on-surface-variant/70 hover:bg-surface-container transition-colors"
                >
                  &ldquo;Prioritize CTOs&rdquo;
                </button>
              </div>
            </div>
          </section>

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
