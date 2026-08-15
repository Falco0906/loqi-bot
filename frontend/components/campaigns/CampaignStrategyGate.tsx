"use client";

import Icon from "../shared/Icon";

type Props = {
  leadsCount: number;
  strategyBusy: boolean;
  researchUrl: string;
  onGenerateStrategy: () => void;
};

/**
 * Strategy section gate for the new lifecycle.
 *
 * Research always precedes strategy. Until leads exist the section shows
 * Step 1 (Research Prospects); once leads are attached it unlocks Step 2
 * (Generate Strategy). The strategy workspace only appears after generation.
 */
export default function CampaignStrategyGate({
  leadsCount,
  strategyBusy,
  researchUrl,
  onGenerateStrategy,
}: Props) {
  const readyForStrategy = leadsCount > 0;

  return (
    <section className="p-6 rounded-xl border border-outline-variant/10 bg-surface-lowest animate-conversation-fade">
      <div className="inline-flex items-center gap-2 mb-3">
        <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-semibold">
          {readyForStrategy ? "Step 2" : "Step 1"}
        </span>
        <span className="w-6 h-px bg-outline-variant/30" />
        <span className="text-[11px] uppercase tracking-widest text-primary font-semibold">
          {readyForStrategy ? "Generate Strategy" : "Research Prospects"}
        </span>
      </div>

      <h4 className="text-xl font-serif text-on-surface font-normal">
        {readyForStrategy
          ? "Your strategy, tailored to the audience."
          : "We need prospects before messaging."}
      </h4>
      <p className="mt-2 text-sm text-on-surface-variant/70 leading-relaxed max-w-lg">
        {readyForStrategy
          ? "Loqi now understands your target audience and can generate messaging tailored to the selected prospects."
          : "We need to understand who this campaign is targeting before building messaging."}
      </p>

      <div className="mt-5">
        {readyForStrategy ? (
          <button
            type="button"
            onClick={onGenerateStrategy}
            disabled={strategyBusy}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-semibold text-on-primary hover:brightness-110 transition-all disabled:opacity-50"
          >
            {strategyBusy ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
                Generating strategy…
              </>
            ) : (
              <>
                <Icon name="auto_awesome" className="text-sm" />
                Generate Strategy
              </>
            )}
          </button>
        ) : (
          <a
            href={researchUrl}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-semibold text-on-primary hover:brightness-110 transition-all"
          >
            <Icon name="travel_explore" className="text-sm" />
            Research prospects
          </a>
        )}
      </div>
    </section>
  );
}