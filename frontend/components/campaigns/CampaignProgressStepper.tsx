"use client";

const STEPS = ["research", "strategy", "drafts", "review", "sending"] as const;

const STEP_META: Record<string, { label: string; icon: string }> = {
  research: { label: "Research", icon: "travel_explore" },
  strategy: { label: "Strategy", icon: "auto_awesome" },
  drafts: { label: "Drafts", icon: "edit_note" },
  review: { label: "Review", icon: "rate_review" },
  sending: { label: "Sending", icon: "rocket_launch" },
};

const SYMBOL_STYLE = { fontVariationSettings: "'FILL' 1" };

/**
 * Compact progress indicator. Purely informational — it never hides or
 * replaces the strategy, leads, or drafts sections below it.
 */
export default function CampaignProgressStepper({ step }: { step: string }) {
  const currentIndex = STEPS.indexOf(step as (typeof STEPS)[number]);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {STEPS.map((s, i) => {
        const meta = STEP_META[s];
        const done = currentIndex > i;
        const isCurrent = currentIndex === i;
        return (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && (
              <span
                className={`w-5 h-px hidden sm:block ${
                  done || isCurrent ? "bg-primary/50" : "bg-outline-variant/25"
                }`}
              />
            )}
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium capitalize transition-colors ${
                done
                  ? "bg-primary/10 text-primary"
                  : isCurrent
                    ? "bg-primary text-on-primary"
                    : "bg-outline-variant/10 text-on-surface-variant/50"
              }`}
            >
              <span className="material-symbols-outlined text-[12px]" style={SYMBOL_STYLE}>
                {done ? "check" : meta.icon}
              </span>
              <span className="hidden sm:inline">{meta.label}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}