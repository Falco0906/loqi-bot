"use client";

import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import { useData } from "../../../lib/hooks/use-data";
import { fetchStrategicUpdate } from "../../../lib/repositories";

function LoadingSkeleton() {
  return (
    <div className="reading-column py-16 flex flex-col gap-16">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-4 animate-skeleton-pulse" style={{ animationDelay: `${i * 0.1}s` }}>
          <div className="h-4 w-1/3 bg-surface-high/50 rounded-lg" />
          <div className="h-8 w-2/3 bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-5/6 bg-surface-high/50 rounded-lg" />
        </div>
      ))}
    </div>
  );
}

export default function StrategicUpdatePage() {
  const { data, loading, error, retry } = useData(fetchStrategicUpdate);

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
          <div className="reading-column py-16 flex flex-col items-center justify-center text-center min-h-[60vh]">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
              <span className="material-symbols-outlined text-3xl">auto_awesome</span>
            </div>
            <p className="text-lg text-on-surface-variant/80 font-medium">No strategic proposal yet</p>
            <p className="mt-1.5 text-sm text-on-surface-variant/50 max-w-sm leading-relaxed">
              When a meaningful decision or market shift arises, I will present my analysis and recommendation here.
            </p>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Header */}
          <header className="animate-conversation-fade">
            <span className="text-[11px] uppercase tracking-[0.2em] text-on-surface-variant/50 font-medium block mb-4">
              Executive Briefing
            </span>
            <h1 className="text-[32px] font-serif text-on-surface mb-4 font-normal">
              Strategic Update
            </h1>
            <p className="text-lg text-on-surface-variant/80 leading-relaxed max-w-xl">
              {data.subtitle}
            </p>
          </header>

          {/* The Understanding */}
          <section className="animate-conversation-fade">
            <div className="bg-surface-lowest p-6 rounded-xl ambient-shadow border border-outline-variant/10">
              <div className="flex items-start gap-4">
                <span className="material-symbols-outlined text-primary mt-1">lightbulb</span>
                <div>
                  <h2 className="text-[11px] uppercase tracking-wider text-on-surface font-semibold mb-2">
                    The Understanding
                  </h2>
                  <p className="text-2xl font-serif italic leading-relaxed text-on-surface font-normal">
                    &ldquo;{data.understanding}&rdquo;
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* Structural Adjustments */}
          <section className="animate-conversation-fade">
            <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-6">
              Structural Adjustments
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {data.adjustments.map((item) => (
                <div
                  key={item.title}
                  className={`bg-surface-lowest p-6 rounded-xl ambient-shadow border border-outline-variant/10 hover:border-primary/30 transition-all duration-300 ${
                    item.colSpan ? "md:col-span-2" : ""
                  }`}
                >
                  <div className={item.colSpan ? "flex items-center gap-4" : ""}>
                    <div className={item.colSpan ? "flex-1" : ""}>
                      <div className="flex justify-between items-start mb-4">
                        <span className="material-symbols-outlined text-primary text-xl">{item.icon}</span>
                        <span className="text-[10px] font-bold text-on-surface-variant/50 tracking-wider">{item.area}</span>
                      </div>
                      <h4 className="text-2xl font-serif text-on-surface font-normal mb-2">{item.title}</h4>
                      <p className="text-sm text-on-surface-variant/70 leading-relaxed">{item.description}</p>
                    </div>
                    {item.colSpan && (
                      <div className="hidden md:block w-1/3 bg-surface-container h-24 rounded-lg border border-dashed border-outline-variant/20 flex items-center justify-center">
                        <span className="material-symbols-outlined text-outline-variant/40 text-3xl">account_balance</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Strategic Impact */}
          <section className="animate-conversation-fade">
            <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-6">
              Strategic Impact
            </h3>
            <div className="space-y-4">
              {data.impacts.map((item) => (
                <div key={item.label} className="flex items-center justify-between py-4 border-b border-outline-variant/10">
                  <div className="flex items-center gap-4">
                    <div className={`w-2 h-2 rounded-full ${item.severity === "high" ? "bg-error" : "bg-secondary"}`} />
                    <span className="text-base text-on-surface">{item.label}</span>
                  </div>
                  <span className="text-xs text-on-surface-variant/70 italic">{item.value}</span>
                </div>
              ))}
            </div>
          </section>

          {/* The Loqi Recommendation */}
          <section className="animate-conversation-fade">
            <div className="bg-on-surface text-primary p-8 rounded-2xl relative overflow-hidden">
              <div className="relative z-10">
                <span className="text-[11px] uppercase tracking-widest text-primary/40 font-semibold mb-2 block">
                  The Loqi Recommendation
                </span>
                <h4 className="text-3xl font-serif leading-relaxed mb-6 font-normal">
                  &ldquo;{data.recommendation}&rdquo;
                </h4>
                <div className="flex gap-4 items-center">
                  <div className="h-1 flex-1 bg-primary/20 rounded-full overflow-hidden">
                    <div className={`h-full bg-primary rounded-full`} style={{ width: `${data.phaseProgress}%` }} />
                  </div>
                  <span className="text-xs font-medium text-primary/60">{data.phaseLabel}</span>
                </div>
              </div>
              <div className="absolute -right-16 -bottom-16 opacity-10 pointer-events-none">
                <span className="material-symbols-outlined text-[200px]">auto_awesome</span>
              </div>
            </div>
          </section>

          {/* What Will Not Change */}
          <section className="animate-conversation-fade grid grid-cols-1 md:grid-cols-2 gap-8">
            {data.stableContinuity.length > 0 && (
              <div>
                <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-4">
                  Stable Continuity
                </h3>
                <ul className="space-y-3">
                  {data.stableContinuity.map((item) => (
                    <li key={item} className="flex items-center gap-3 text-base text-on-surface">
                      <span className="material-symbols-outlined text-secondary text-lg">check_circle</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data.affectedAreas.length > 0 && (
              <div>
                <h3 className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold mb-4">
                  Affected Areas
                </h3>
                <div className="flex flex-wrap gap-2">
                  {data.affectedAreas.map((area) => (
                    <span key={area} className="px-3 py-1.5 bg-surface-high rounded-full text-xs text-on-surface-variant/80">
                      {area}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      </AppPage>

      {/* Sticky Bottom Action Bar */}
      <footer className="fixed bottom-0 left-64 right-0 p-6 flex justify-center z-50 bg-gradient-to-t from-charcoal via-charcoal/90 to-transparent pointer-events-none">
        <div className="flex items-center gap-4 bg-surface rounded-full px-4 py-3 ambient-shadow border border-outline-variant/10 pointer-events-auto">
          <button className="px-8 py-3 bg-primary text-on-primary rounded-full text-xs font-semibold uppercase tracking-wider hover:scale-[0.98] active:scale-95 transition-transform">
            Apply Strategy
          </button>
          <button className="px-8 py-3 bg-surface text-on-surface border border-outline-variant/30 rounded-full text-xs font-semibold uppercase tracking-wider hover:bg-surface-container-low transition-colors">
            Modify Plan
          </button>
          <button className="px-6 py-3 text-on-surface-variant/70 hover:text-error transition-colors text-xs font-semibold uppercase tracking-wider">
            Cancel
          </button>
        </div>
      </footer>
    </WorkspaceContainer>
  );
}
