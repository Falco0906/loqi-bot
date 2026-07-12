"use client";

import { useState } from "react";
import Icon from "../shared/Icon";
import CampaignStatusBadge from "../campaigns/CampaignStatusBadge";

type Campaign = {
  id: string;
  name: string;
  lead_count: number;
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
  onApprove: (campaignName: string) => void;
  onBack: () => void;
  onCancel: () => void;
  onEditLater: (campaignName: string) => void;
};

export default function StrategyApproval({
  campaigns,
  overallRecommendation,
  totalLeads,
  onApprove,
  onBack,
  onCancel,
  onEditLater,
}: Props) {
  const [campaignName, setCampaignName] = useState("");
  const nameValid = campaignName.trim().length > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden animate-fade-in">
      <div className="flex-1 overflow-y-auto px-6 pb-40">
        <div className="max-w-4xl mx-auto pt-8">
          <div className="flex items-center gap-3 mb-8">
            <button
              onClick={onBack}
              className="p-1.5 rounded-lg hover:bg-surface-high text-on-surface-variant/60 hover:text-on-surface transition-all duration-150 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
            >
              <Icon name="chevron_right" className="rotate-180 text-lg" />
            </button>
            <div className="w-10 h-10 rounded-xl bg-success/10 flex items-center justify-center">
              <Icon name="check_circle" className="text-success text-xl" />
            </div>
            <div>
              <h2 className="text-headline-md text-on-surface font-bold">Approve Strategy</h2>
              <p className="text-body-md text-on-surface-variant/60">
                Review the campaign plan before generating drafts
              </p>
            </div>
          </div>

          {/* Campaign Name */}
          <div className="mb-8 card-base p-5 border-2 border-primary/20 bg-primary-container/5">
            <label className="text-label-sm text-primary/80 uppercase tracking-wider font-semibold block mb-2 flex items-center gap-1.5">
              <Icon name="edit_note" className="text-sm" />
              Name Your Campaign
            </label>
            <input
              type="text"
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value)}
              placeholder="e.g. Q3 E-Commerce Outreach"
              className={`w-full rounded-xl border-2 bg-surface-low px-4 py-3 text-body-md text-on-surface outline-none transition-all duration-150 placeholder:text-on-surface-variant/30 ${
                campaignName.trim()
                  ? "border-primary/40 focus:border-primary"
                  : "border-error/30 focus:border-error"
              }`}
              autoFocus
            />
            {!campaignName.trim() && (
              <p className="text-[11px] text-error/70 mt-1.5 flex items-center gap-1">
                <Icon name="warning" className="text-xs" />
                A campaign name is required before approving
              </p>
            )}
          </div>

          {/* Summary stats */}
          <div className="grid grid-cols-4 gap-4 mb-8">
            {[
              { label: "Total Campaigns", value: campaigns.length, icon: "campaign" },
              { label: "Total Leads", value: totalLeads, icon: "groups" },
              { label: "Est. Drafts", value: totalLeads, icon: "edit_note" },
              { label: "Est. Review Time", value: `${Math.ceil(totalLeads * 3)} min`, icon: "timer" },
            ].map((s) => (
              <div
                key={s.label}
                className="card-base p-4 text-center"
              >
                <Icon name={s.icon} className="text-primary text-lg mb-2" />
                <p className="text-headline-sm text-on-surface font-bold">{s.value}</p>
                <p className="text-label-sm text-on-surface-variant/60">{s.label}</p>
              </div>
            ))}
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
                <p className="text-body-md text-on-surface leading-relaxed whitespace-pre-line">
                  {overallRecommendation}
                </p>
              </div>
            </div>
          </div>

          {/* Campaign cards */}
          <div className="space-y-4 mb-8">
            {campaigns.map((c, i) => (
              <div
                key={c.id}
                className="card-base overflow-hidden"
              >
                <div className="px-5 py-4 border-b border-outline-variant/10 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Icon name="campaign" className="text-primary text-sm" />
                    </div>
                    <div>
                      <p className="text-body-md text-on-surface font-bold">
                        Campaign {String.fromCharCode(65 + i)}
                      </p>
                      <p className="text-label-sm text-on-surface-variant/60">{c.name}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="text-headline-sm text-on-surface font-bold">{c.lead_count}</p>
                      <p className="text-label-sm text-on-surface-variant/60">Leads</p>
                    </div>
                  </div>
                </div>
                <div className="px-5 py-4 space-y-3">
                  <div className="bg-surface/50 rounded-xl px-4 py-3">
                    <p className="text-label-sm text-on-surface-variant/60 mb-1">Why grouped here</p>
                    <p className="text-body-sm text-on-surface">{c.reason}</p>
                  </div>
                  <div className="bg-primary-container/5 rounded-xl px-4 py-3 border border-primary/10">
                    <p className="text-label-sm text-primary/70 mb-1">Suggested Messaging</p>
                    <p className="text-body-sm text-on-surface">{c.messaging_angle}</p>
                  </div>
                  <div className="bg-surface-low rounded-xl px-4 py-3 border border-outline-variant/5">
                    <p className="text-label-sm text-on-surface-variant/60 mb-1">Message Theme</p>
                    <p className="text-body-sm text-on-surface italic opacity-80">
                      &ldquo;{c.message_theme}&rdquo;
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-outline-variant/10 bg-surface-lowest px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <p className="text-label-sm text-on-surface-variant/40">
            {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} &middot; ~{Math.ceil(totalLeads * 3)} min review time
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={onCancel}
              className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-error/40 hover:text-error active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-error/60 focus-visible:outline-offset-2"
            >
              Cancel
            </button>
            <button
              onClick={() => onEditLater(campaignName)}
              disabled={!nameValid}
              className="px-5 py-2.5 rounded-lg border border-outline-variant/20 text-on-surface font-medium hover:border-primary/40 hover:text-primary active:scale-[0.97] transition-all duration-150 text-sm focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 disabled:opacity-40"
            >
              Edit Later
            </button>
            <button
              onClick={() => onApprove(campaignName)}
              disabled={!nameValid}
              className="px-6 py-2.5 rounded-lg bg-success text-white font-bold hover:brightness-110 active:scale-[0.97] transition-all duration-150 text-sm flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-success/60 focus-visible:outline-offset-2 disabled:opacity-40"
            >
              <Icon name="check_circle" className="text-base" />
              Approve Strategy
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
