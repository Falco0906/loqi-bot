"use client";

import { useState } from "react";
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
  onCustomize: (campaigns: Campaign[], recommendation: string) => void;
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

type EditState = {
  editing: boolean;
  campaigns: Campaign[];
  recommendation: string;
};

export default function CampaignPlanner({
  campaigns,
  overallRecommendation,
  totalLeads,
  onAccept,
  onCustomize,
  onCancel,
}: Props) {
  const [edit, setEdit] = useState<EditState | null>(null);

  const handleStartCustomize = () => {
    setEdit({
      editing: true,
      campaigns: campaigns.map((c) => ({ ...c })),
      recommendation: overallRecommendation,
    });
  };

  const handleSaveCustomize = () => {
    if (!edit) return;
    onCustomize(edit.campaigns, edit.recommendation);
    setEdit(null);
  };

  const handleCancelCustomize = () => {
    setEdit(null);
  };

  const updateCampaign = (index: number, field: string, value: string | number) => {
    if (!edit) return;
    const updated = [...edit.campaigns];
    updated[index] = { ...updated[index], [field]: value };
    setEdit({ ...edit, campaigns: updated });
  };

  const displayCampaigns = edit ? edit.campaigns : campaigns;
  const displayRecommendation = edit ? edit.recommendation : overallRecommendation;

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
                  {edit ? "Customize Campaigns" : "Campaign Strategy"}
                </h2>
                <p className="text-body-md text-on-surface-variant/60">
                  {edit
                    ? "Edit campaign details before launching"
                    : `AI analysis of ${totalLeads} selected lead${totalLeads !== 1 ? "s" : ""}`}
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
              <div className="flex-1 min-w-0">
                <p className="text-label-sm text-primary/70 uppercase tracking-wider font-medium mb-1">
                  Overall Recommendation
                </p>
                {edit ? (
                  <textarea
                    value={displayRecommendation}
                    onChange={(e) => setEdit({ ...edit, recommendation: e.target.value })}
                    className="w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2 text-body-md text-on-surface outline-none focus:border-primary/50 resize-none min-h-[80px]"
                  />
                ) : (
                  <div className="text-body-md text-on-surface leading-relaxed whitespace-pre-line">
                    {displayRecommendation}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Campaign Cards */}
          {displayCampaigns.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <Icon name="insights" className="text-4xl" />
              </div>
              <p className="text-body-lg text-on-surface-variant/60">
                No campaign groupings found
              </p>
              <p className="mt-1 text-body-md text-on-surface-variant/40">
                The selected leads may not have enough signals to group into campaigns.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              {displayCampaigns.map((c, i) => (
                <div
                  key={c.id}
                  className="card-base overflow-hidden hover:border-primary/20 transition-all"
                >
                  <div className="px-5 py-4 border-b border-outline-variant/10 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                        <Icon name="campaign" className="text-primary text-lg" />
                      </div>
                      <div>
                        {edit ? (
                          <input
                            type="text"
                            value={c.name}
                            onChange={(e) => updateCampaign(i, "name", e.target.value)}
                            className="text-body-lg font-bold text-on-surface bg-surface-lowest border border-outline-variant/20 rounded-lg px-2 py-1 outline-none focus:border-primary/50 w-full"
                          />
                        ) : (
                          <>
                            <h3 className="text-body-lg text-on-surface font-bold">
                              Campaign {String.fromCharCode(65 + i)}
                            </h3>
                            <p className="text-label-sm text-on-surface-variant/60">{c.name}</p>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-headline-sm text-on-surface font-bold">{c.lead_count}</p>
                        <p className="text-label-sm text-on-surface-variant/60">
                          {c.lead_count === 1 ? "Lead" : "Leads"}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="px-5 py-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-label-sm text-on-surface-variant uppercase tracking-wider font-medium">
                        {c.primary_signal === "primary_signal" ? "Buying Signal" : c.primary_signal === "industry" ? "Industry Match" : "Signal"}
                      </span>
                      <PriorityStars n={c.priority} />
                    </div>

                    <div className="bg-surface/50 rounded-xl px-4 py-3 border border-outline-variant/5">
                      <p className="text-label-sm text-on-surface-variant/60 mb-1">Why grouped here</p>
                      {edit ? (
                        <textarea
                          value={c.reason}
                          onChange={(e) => updateCampaign(i, "reason", e.target.value)}
                          className="w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-2 py-1 text-body-sm text-on-surface outline-none focus:border-primary/50 resize-none min-h-[40px]"
                        />
                      ) : (
                        <p className="text-body-sm text-on-surface">{c.reason}</p>
                      )}
                    </div>

                    <div className="bg-primary-container/5 rounded-xl px-4 py-3 border border-primary/10">
                      <p className="text-label-sm text-primary/70 mb-1">Suggested Messaging</p>
                      {edit ? (
                        <textarea
                          value={c.messaging_angle}
                          onChange={(e) => updateCampaign(i, "messaging_angle", e.target.value)}
                          className="w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-2 py-1 text-body-sm text-on-surface outline-none focus:border-primary/50 resize-none min-h-[40px]"
                        />
                      ) : (
                        <p className="text-body-sm text-on-surface">{c.messaging_angle}</p>
                      )}
                    </div>

                    <div className="bg-surface-low rounded-xl px-4 py-3 border border-outline-variant/5">
                      <p className="text-label-sm text-on-surface-variant/60 mb-1">Message Theme Preview</p>
                      {edit ? (
                        <textarea
                          value={c.message_theme}
                          onChange={(e) => updateCampaign(i, "message_theme", e.target.value)}
                          className="w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-2 py-1 text-body-sm text-on-surface italic outline-none focus:border-primary/50 resize-none min-h-[40px]"
                        />
                      ) : (
                        <p className="text-body-sm text-on-surface italic opacity-80">
                          &ldquo;{c.message_theme}&rdquo;
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-outline-variant/10 bg-surface-lowest px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <p className="text-label-sm text-on-surface-variant/40">
            {displayCampaigns.length} campaign{displayCampaigns.length !== 1 ? "s" : ""} &middot;{" "}
            {totalLeads} lead{totalLeads !== 1 ? "s" : ""}
          </p>
          <div className="flex items-center gap-3">
            {edit ? (
              <>
                <button
                  onClick={handleCancelCustomize}
                  className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-error/40 hover:text-error active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-error/60 focus-visible:outline-offset-2"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveCustomize}
                  className="px-6 py-2.5 rounded-lg bg-primary text-on-primary font-bold hover:brightness-110 active:scale-[0.97] transition-all duration-150 text-sm flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                >
                  <Icon name="check_circle" className="text-base" />
                  Save Changes
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={onCancel}
                  className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-error/40 hover:text-error active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-error/60 focus-visible:outline-offset-2"
                >
                  Cancel
                </button>
                <button
                  onClick={handleStartCustomize}
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
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
