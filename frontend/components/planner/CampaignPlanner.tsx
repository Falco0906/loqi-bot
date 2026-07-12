"use client";

import Icon from "../shared/Icon";

type Campaign = {
  id: string;
  name: string;
  lead_count: number;
  leads: unknown[];
  primary_signal: string;
  reason: string;
  messaging_angle: string;
  priority: number;
  message_theme: string;
};

type Props = {
  campaigns: Campaign[];
  overallRecommendation: string;
  totalLeads: number;
  onAccept: () => void;
  onCustomize: () => void;
  onCancel: () => void;
};

function PriorityStars({ n }: { n: number }) {
  return (
    <span className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Icon
          key={i}
          name="star"
          className={`text-xs ${i <= n ? "text-warning" : "text-outline-variant/20"}`}
        />
      ))}
    </span>
  );
}

function CampaignStrategyCard({
  campaign,
  index,
}: {
  campaign: Campaign;
  index: number;
}) {
  const signalLabels: Record<string, string> = {
    primary_signal: "Buying Signal",
    industry: "Industry Match",
    mixed: "Mixed Signals",
  };

  return (
    <div className="card-base overflow-hidden hover:border-primary/20 transition-all">
      <div className="px-5 py-4 border-b border-outline-variant/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Icon name="campaign" className="text-primary text-lg" />
          </div>
          <div>
            <h3 className="text-body-lg text-on-surface font-bold">
              Campaign {String.fromCharCode(65 + index)}
            </h3>
            <p className="text-label-sm text-on-surface-variant/60">
              {campaign.name}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-headline-sm text-on-surface font-bold">
              {campaign.lead_count}
            </p>
            <p className="text-label-sm text-on-surface-variant/60">
              {campaign.lead_count === 1 ? "Lead" : "Leads"}
            </p>
          </div>
        </div>
      </div>

      <div className="px-5 py-4 space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-label-sm text-on-surface-variant uppercase tracking-wider font-medium">
            {signalLabels[campaign.primary_signal] || "Signal"}
          </span>
          <PriorityStars n={campaign.priority} />
        </div>

        <div className="bg-surface/50 rounded-xl px-4 py-3 border border-outline-variant/5">
          <p className="text-label-sm text-on-surface-variant/60 mb-1">
            Why grouped here
          </p>
          <p className="text-body-sm text-on-surface">{campaign.reason}</p>
        </div>

        <div className="bg-primary-container/5 rounded-xl px-4 py-3 border border-primary/10">
          <p className="text-label-sm text-primary/70 mb-1">
            Suggested Messaging
          </p>
          <p className="text-body-sm text-on-surface">
            {campaign.messaging_angle}
          </p>
        </div>

        <div className="bg-surface-low rounded-xl px-4 py-3 border border-outline-variant/5">
          <p className="text-label-sm text-on-surface-variant/60 mb-1">
            Message Theme Preview
          </p>
          <p className="text-body-sm text-on-surface italic opacity-80">
            &ldquo;{campaign.message_theme}&rdquo;
          </p>
        </div>
      </div>
    </div>
  );
}

export default function CampaignPlanner({
  campaigns,
  overallRecommendation,
  totalLeads,
  onAccept,
  onCustomize,
  onCancel,
}: Props) {
  return (
    <div className="flex flex-col h-full overflow-hidden animate-fade-in">
      <div className="flex-1 overflow-y-auto px-6 pb-40">
        <div className="max-w-4xl mx-auto pt-8">
          {/* Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                <Icon name="auto_awesome" className="text-primary text-xl" />
              </div>
              <div>
                <h2 className="text-headline-md text-on-surface font-bold">
                  Campaign Strategy
                </h2>
                <p className="text-body-md text-on-surface-variant/60">
                  AI analysis of {totalLeads} selected lead
                  {totalLeads !== 1 ? "s" : ""}
                </p>
              </div>
            </div>
          </div>

          {/* Overall Recommendation */}
          <div className="mb-8 card-base border-primary/15 bg-primary-container/5 px-6 py-5">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <Icon name="lightbulb" className="text-primary text-base" />
              </div>
              <div>
                <p className="text-label-sm text-primary/70 uppercase tracking-wider font-medium mb-1">
                  Overall Recommendation
                </p>
                <div className="text-body-md text-on-surface leading-relaxed whitespace-pre-line">
                  {overallRecommendation}
                </div>
              </div>
            </div>
          </div>

          {/* Campaign Cards */}
          {campaigns.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <Icon name="insights" className="text-4xl" />
              </div>
              <p className="text-body-lg text-on-surface-variant/60">
                No campaign groupings found
              </p>
              <p className="mt-1 text-body-md text-on-surface-variant/40">
                The selected leads may not have enough signals to group into
                campaigns.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              {campaigns.map((c, i) => (
                <CampaignStrategyCard
                  key={c.id}
                  campaign={c}
                  index={i}
                />
              ))}
            </div>
          )}

          {/* Customize shell (Phase 2.5 placeholder) */}
          <div className="mt-8 card-base border-dashed border-outline-variant/20 bg-surface-lowest/50 px-6 py-5">
            <div className="flex items-center gap-3 mb-3">
              <Icon name="tune" className="text-on-surface-variant/40 text-base" />
              <p className="text-label-sm text-on-surface-variant/40 uppercase tracking-wider font-medium">
                Customize Campaigns
              </p>
              <span className="text-[10px] uppercase tracking-wider text-tertiary ml-auto">
                Phase 2.5
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {["Rename Campaign", "Merge Campaigns", "Split Campaign", "Move Leads", "Delete Campaign"].map(
                (action) => (
                  <button
                    key={action}
                    disabled
                    className="px-3 py-1.5 rounded-lg border border-outline-variant/10 text-label-sm text-on-surface-variant/30 cursor-not-allowed"
                  >
                    {action}
                  </button>
                ),
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-outline-variant/10 bg-surface-lowest px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <p className="text-label-sm text-on-surface-variant/40">
            {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} &middot;{" "}
            {totalLeads} lead{totalLeads !== 1 ? "s" : ""}
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={onCancel}
              className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-error/40 hover:text-error active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-error/60 focus-visible:outline-offset-2"
            >
              Cancel
            </button>
            <button
              onClick={onCustomize}
              className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-primary/40 hover:text-primary active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
            >
              Customize Plan
            </button>
            <button
              onClick={onAccept}
              className="px-6 py-2.5 rounded-lg bg-primary text-on-primary font-bold hover:brightness-110 active:scale-[0.97] transition-all duration-150 text-sm flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
            >
              <Icon name="check_circle" className="text-base" />
              Accept Campaign Plan
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
