"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listCampaigns, getCampaignSummary } from "../../../lib/api";
import PageContainer from "../../../components/shared/PageContainer";
import Icon from "../../../components/shared/Icon";
import CampaignStatusBadge from "../../../components/campaigns/CampaignStatusBadge";
import { usePageContext } from "../../../hooks/usePageContext";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

type CampaignInfo = {
  id: string;
  name: string;
  status: string;
  lead_count: number;
  pending_drafts: number;
};

export default function CampaignIntelligencePage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([]);

  usePageContext("Campaign Intelligence", {
    active_campaigns: campaigns.filter((c) => c.status !== "archived" && c.status !== "completed").length,
    total_campaigns: campaigns.length,
    pending_drafts: campaigns.reduce((s, c) => s + c.pending_drafts, 0),
  });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  useEffect(() => {
    if (!sessionToken) return;
    getCampaignSummary(sessionToken).then((res) => {
      if (res.ok) setCampaigns(res.campaigns);
    }).catch(() => {});
  }, [sessionToken]);

  const activeCampaigns = campaigns.filter((c) => c.status !== "archived" && c.status !== "completed");
  const hasDrafts = campaigns.some((c) => c.pending_drafts > 0);

  const recommendations = [
    ...(hasDrafts
      ? [{
          id: "review-drafts",
          icon: "edit_note" as const,
          title: "Drafts pending review",
          description: "Some campaigns have unapproved drafts. Review and approve them to keep your pipeline moving.",
          action: "Review Drafts",
          href: "/draft",
          color: "text-secondary" as const,
        }]
      : []),
    ...(activeCampaigns.length >= 2
      ? [{
          id: "compare",
          icon: "insights" as const,
          title: "Compare campaign performance",
          description: `${activeCampaigns[0]?.name || "Campaign A"} and ${activeCampaigns[1]?.name || "Campaign B"} have different outreach strategies. Consider optimizing based on response patterns.`,
          action: "View Campaigns",
          href: "/campaigns",
          color: "text-primary" as const,
        }]
      : []),
    ...(activeCampaigns.some((c) => c.status === "planning")
      ? [{
          id: "approve-strategy",
          icon: "check_circle" as const,
          title: "Strategies awaiting approval",
          description: `${activeCampaigns.filter((c) => c.status === "planning").length} campaign${activeCampaigns.filter((c) => c.status === "planning").length !== 1 ? "s" : ""} ${activeCampaigns.filter((c) => c.status === "planning").length !== 1 ? "are" : "is"} waiting for strategy approval. Approve to start drafting.`,
          action: "Review Strategy",
          href: `/campaigns/${activeCampaigns.find((c) => c.status === "planning")?.id}`,
          color: "text-warning" as const,
        }]
      : []),
    {
      id: "new-campaign",
      icon: "add_circle" as const,
      title: "Start a new campaign",
      description: "Find fresh leads in Discovery and run them through the AI Campaign Planner for a personalized outreach strategy.",
      action: "Discover Leads",
      href: "/discovery",
      color: "text-tertiary" as const,
    },
  ];

  return (
    <PageContainer>
      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
          <Icon name="insights" className="text-primary text-xl" />
        </div>
        <div>
          <h1 className="text-headline-md text-on-surface font-bold">Campaign Intelligence</h1>
          <p className="text-body-md text-on-surface-variant/60">
            AI recommendations based on your active campaigns
          </p>
        </div>
      </div>

      {/* Recommendations */}
      <div className="grid gap-4 lg:grid-cols-2 mb-10">
        {recommendations.map((r) => (
          <Link
            key={r.id}
            href={r.href}
            className="rounded-2xl border border-outline-variant/10 bg-surface-lowest p-6 transition-all hover:border-primary/20 hover:-translate-y-0.5"
          >
            <div className="flex items-start gap-4">
              <div className={`w-10 h-10 rounded-xl bg-surface/50 flex items-center justify-center shrink-0 ${r.color}`}>
                <Icon name={r.icon} className="text-xl" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-body-md text-on-surface font-bold mb-1">{r.title}</h3>
                <p className="text-label-sm text-on-surface-variant/60 leading-relaxed">{r.description}</p>
                <div className="mt-3">
                  <span className={`inline-flex items-center gap-1 text-label-sm font-bold ${r.color} hover:underline`}>
                    {r.action}
                    <Icon name="chevron_right" className="text-sm" />
                  </span>
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Active campaigns overview */}
      {activeCampaigns.length > 0 && (
        <div>
          <h2 className="text-label-sm text-on-surface-variant/40 uppercase tracking-wider font-medium mb-4">
            Active Campaigns
          </h2>
          <div className="grid gap-3 lg:grid-cols-2">
            {activeCampaigns.map((c) => (
              <Link
                key={c.id}
                href={`/campaigns/${c.id}`}
                className="rounded-xl border border-outline-variant/10 bg-surface-lowest px-5 py-4 flex items-center justify-between hover:border-primary/20 transition-all"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-lg bg-primary-container/10 flex items-center justify-center shrink-0">
                    <Icon name="campaign" className="text-primary text-base" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-body-md text-on-surface font-bold truncate">{c.name}</p>
                    <p className="text-label-sm text-on-surface-variant/60">
                      {c.lead_count} lead{c.lead_count !== 1 ? "s" : ""}
                      {c.pending_drafts > 0 ? ` \u00b7 ${c.pending_drafts} draft${c.pending_drafts !== 1 ? "s" : ""} pending` : ""}
                    </p>
                  </div>
                </div>
                <CampaignStatusBadge status={c.status} />
              </Link>
            ))}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
