"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { getMissionControl } from "../../lib/api";
import type { MCSummary } from "../../lib/api";
import Icon from "../shared/Icon";
import { usePageContext } from "../../hooks/usePageContext";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const STATUS_STAGE: Record<string, number> = {
  planning: 1,
  ready: 2,
  generating: 2,
  draft_review: 3,
  ready_to_send: 4,
  completed: 5,
  archived: 5,
};

const STAGE_LABELS = ["Discovery", "Drafts", "Review", "Launch"];

function campaignStage(status: string): number {
  return STATUS_STAGE[status] || 0;
}

function campaignProgress(status: string): number {
  return Math.round(((STATUS_STAGE[status] || 0) / 5) * 100);
}

function nextStep(status: string): string {
  const steps: Record<string, string> = {
    planning: "Define strategy and set messaging",
    ready: "Generate drafts for your leads",
    generating: "Draft generation in progress",
    draft_review: "Review and approve pending drafts",
    ready_to_send: "Launch campaign outreach",
    completed: "Campaign finished",
    archived: "Archived",
  };
  return steps[status] || "Continue working";
}

function isReady(status: string): boolean {
  return status === "ready_to_send" || status === "draft_review";
}

function shortTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (isToday) return time;
  return `${d.toLocaleDateString("en-US", { weekday: "short" })} ${time}`;
}

const JOB_TYPE_LABELS: Record<string, string> = {
  search: "Searching for leads",
  generate_drafts: "Generating drafts",
};

function buildBriefLines(data: MCSummary): string[] {
  if (data.brief?.lines && data.brief.lines.length > 0) {
    return data.brief.lines;
  }
  return ["Everything looks up to date."];
}

export default function MissionControlDashboard() {
  const [data, setData] = useState<MCSummary | null>(null);
  const [loading, setLoading] = useState(true);

  usePageContext("Mission Control", {
    campaign_count: data?.campaign_count ?? 0,
    campaigns_ready: data?.kpis.campaigns_ready ?? 0,
    pending_reviews: data?.draft_counts.pending ?? 0,
    approved_drafts: data?.draft_counts.approved ?? 0,
    total_leads: data?.total_leads ?? 0,
    needs_attention: data?.needs_attention.length ?? 0,
    recommendations: data?.recommendations.length ?? 0,
    top_priority: data?.workspace_analysis?.campaign_priorities?.[0]?.name ?? "",
    health: data?.workspace_analysis?.workspace_health?.overall_health ?? "",
  });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (!token) { setLoading(false); return; }
    getMissionControl(token)
      .then((res) => { if (res.ok) setData(res); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const briefLines = useMemo(() => data ? buildBriefLines(data) : [], [data]);

  const actionButtons = useMemo(() => {
    const btns: { label: string; href: string; icon: string }[] = [];
    if (!data) return btns;
    const hasReview = data.needs_attention.some((n) => n.action === "review");
    const hasLaunch = data.needs_attention.some((n) => n.action === "launch");
    const hasPlanning = data.campaigns.some((c) => c.status === "planning" && c.lead_count > 0);
    if (hasReview) btns.push({ label: "Review Drafts", href: "/draft", icon: "edit_note" });
    else if (hasLaunch) btns.push({ label: "Launch Campaign", href: "/campaigns", icon: "rocket_launch" });
    else if (hasPlanning) btns.push({ label: "Continue Planning", href: "/campaigns", icon: "campaign" });
    if (data.campaigns.length > 0) btns.push({ label: "View Campaigns", href: "/campaigns", icon: "campaign" });
    btns.push({ label: "Find More Leads", href: "/discovery", icon: "explore" });
    return btns;
  }, [data]);

  const runningJobs = useMemo(() => {
    if (!data?.active_jobs) return [];
    return (data.active_jobs as Array<Record<string, unknown>>).filter(
      (j) => j.status === "queued" || j.status === "running"
    );
  }, [data]);

  if (loading) {
    return (
      <div className="max-w-[1200px] mx-auto px-6 pb-20 animate-fade-in">
        <div className="mb-14 space-y-3">
          <div className="h-11 w-64 animate-skeleton-pulse bg-surface-high/30 rounded-lg" />
          <div className="h-5 w-[420px] animate-skeleton-pulse bg-surface-high/20 rounded-lg" />
          <div className="h-5 w-72 animate-skeleton-pulse bg-surface-high/20 rounded-lg" />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-12">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-24 rounded-xl bg-surface-high/15 animate-skeleton-pulse" />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
          <div className="lg:col-span-2 h-64 rounded-xl bg-surface-high/15 animate-skeleton-pulse" />
          <div className="h-80 rounded-xl bg-surface-high/15 animate-skeleton-pulse" />
        </div>
        <div className="h-56 rounded-xl bg-surface-high/15 animate-skeleton-pulse mb-10" />
        <div className="h-40 rounded-xl bg-surface-high/15 animate-skeleton-pulse" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1200px] mx-auto px-6 pb-24 animate-fade-in">
        <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
          <div className="absolute top-1/4 -left-20 w-96 h-96 bg-primary/6 blur-[120px] rounded-full" />
          <div className="absolute bottom-1/4 -right-20 w-80 h-80 bg-secondary/4 blur-[120px] rounded-full" />
        </div>

        {/* ── 1. Executive Brief ── */}
        <section className="mb-14 pt-6">
          <h1 className="text-[36px] font-bold text-on-surface leading-tight tracking-tight">
            {greeting()}.
          </h1>
          {data && briefLines.length > 0 && (
            <div className="mt-4 space-y-1.5">
              {briefLines.map((line, i) => (
                <p key={i} className={`text-body-lg text-on-surface-variant/70 max-w-2xl leading-relaxed ${i === briefLines.length - 1 ? "text-primary/80 font-medium" : ""}`}>
                  {line}
                </p>
              ))}
            </div>
          )}
          {actionButtons.length > 0 && (
            <div className="flex flex-wrap gap-3 mt-6">
              <Link
                href={actionButtons[0].href}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-on-primary text-sm font-bold transition-all duration-200 hover:brightness-110 hover:-translate-y-0.5 active:scale-[0.97] shadow-lg shadow-primary/15"
              >
                <Icon name={actionButtons[0].icon} className="text-base" />
                {actionButtons[0].label}
              </Link>
              {actionButtons.slice(1).map((btn) => (
                <Link
                  key={btn.label}
                  href={btn.href}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-on-surface-variant/70 hover:text-on-surface hover:bg-surface-high/20 transition-all duration-200 active:scale-[0.97]"
                >
                  <Icon name={btn.icon} className="text-base" />
                  {btn.label}
                </Link>
              ))}
            </div>
          )}
        </section>

        {!data || (data.campaign_count === 0 && data.draft_counts.total === 0 && runningJobs.length === 0) ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/20 flex items-center justify-center text-on-surface-variant/30 mb-5">
              <Icon name="dashboard" className="text-3xl" />
            </div>
            <h2 className="text-headline-md text-on-surface font-semibold">No campaigns yet</h2>
            <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm">
              Everything is quiet. Start by discovering leads for your first campaign.
            </p>
            <Link
              href="/discovery"
              className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-on-primary text-sm font-bold transition-all duration-200 hover:brightness-110 hover:-translate-y-0.5 active:scale-[0.97]"
            >
              <Icon name="explore" className="text-base" />
              Find Leads
            </Link>
          </div>
        ) : (
          <>
            {/* ── KPI Grid ── */}
            {data && data.campaign_count > 0 && (
              <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-12">
                <KpiCard
                  icon="rocket_launch"
                  label="Campaigns Ready"
                  value={String(data.kpis.campaigns_ready)}
                  sub={data.kpis.campaigns_ready === 1 ? "Ready to launch" : "Ready to launch"}
                />
                <KpiCard
                  icon="rate_review"
                  label="Pending Review"
                  value={String(data.kpis.pending_reviews)}
                  sub={data.kpis.pending_reviews === 1 ? "Requires approval" : "Require approval"}
                />
                <KpiCard
                  icon="reply"
                  label="Predicted Reply Rate"
                  value={`${data.kpis.estimated_reply_rate}%`}
                  sub="Estimated"
                />
                <KpiCard
                  icon="settings_suggest"
                  label="Running Jobs"
                  value={String(runningJobs.length)}
                  sub={runningJobs.length === 1 ? "In progress" : "In progress"}
                />
              </section>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-12">
              {/* ── 2. Continue Working ── */}
              <section className="lg:col-span-2">
                <h2 className="text-headline-sm text-on-surface font-bold mb-5">Continue Working</h2>
                {data && data.campaigns.length === 0 ? (
                  <div className="rounded-xl bg-surface-lowest/30 p-8 text-center">
                    <p className="text-body-md text-on-surface-variant/50">No campaigns are currently in progress.</p>
                    <p className="text-sm text-on-surface-variant/40 mt-1">
                      <Link href="/discovery" className="text-primary hover:underline">Start a new lead search.</Link>
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {data && data.campaigns.slice(0, 5).map((c, i) => (
                      <ContinueCard key={c.id} campaign={c} index={i} />
                    ))}
                    {data && data.campaign_count > 5 && (
                      <Link
                        href="/campaigns"
                        className="block text-center py-3.5 rounded-xl text-sm font-medium text-on-surface-variant/50 hover:text-primary transition-colors"
                      >
                        View all {data.campaign_count} campaigns
                      </Link>
                    )}
                  </div>
                )}
              </section>

              {/* ── Right Column ── */}
              <section className="space-y-8">
                {data && data.needs_attention.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-1.5 h-1.5 rounded-full bg-error" />
                      <h2 className="text-headline-sm text-on-surface font-bold">Needs Attention</h2>
                    </div>
                    <div className="space-y-2.5">
                      {data.needs_attention.map((item, i) => (
                        <NeedAttentionCard key={`${item.type}-${i}`} item={item} index={i} />
                      ))}
                    </div>
                  </div>
                )}

                {data && data.needs_attention.length === 0 && data.campaign_count > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-1.5 h-1.5 rounded-full bg-success" />
                      <h2 className="text-headline-sm text-on-surface font-bold">Needs Attention</h2>
                    </div>
                    <div className="rounded-xl bg-surface-lowest/30 p-6 text-center">
                      <p className="text-sm text-on-surface-variant/50">Everything looks good.</p>
                      <p className="text-xs text-on-surface-variant/40 mt-0.5">No immediate action required.</p>
                    </div>
                  </div>
                )}

                {runningJobs.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-4">
                      <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                      <h2 className="text-headline-sm text-on-surface font-bold">Background Jobs</h2>
                    </div>
                    <div className="space-y-2.5">
                      {runningJobs.slice(0, 3).map((job) => (
                        <JobCard key={job.id as string} job={job as Record<string, unknown>} />
                      ))}
                    </div>
                  </div>
                )}

                {/* ── 3. AI Recommendations ── */}
                <div>
                  <h2 className="text-headline-sm text-on-surface font-bold mb-4">Recommendations</h2>
                  <div className="space-y-2.5">
                    {data && data.recommendations.length === 0 ? (
                      <div className="rounded-xl bg-surface-lowest/30 p-6 text-center">
                        <p className="text-sm text-on-surface-variant/50">
                          Loqi doesn&apos;t have any recommendations right now.
                        </p>
                        <p className="text-xs text-on-surface-variant/40 mt-0.5">Continue building your pipeline.</p>
                      </div>
                    ) : (
                      data && data.recommendations.slice(0, 3).map((rec, i) => (
                        <RecommendationCard key={`${rec.type}-${i}`} rec={rec} index={i} />
                      ))
                    )}
                  </div>
                </div>
              </section>
            </div>

            {/* ── 4. Live Activity ── */}
            {data && data.live_activity.length > 0 && (
              <section className="mb-12">
                <h2 className="text-headline-sm text-on-surface font-bold mb-5">Activity</h2>
                <div className="space-y-0">
                  {data.live_activity.slice(0, 10).map((item, i) => (
                    <ActivityRow key={`${item.type}-${i}`} item={item} index={i} />
                  ))}
                </div>
              </section>
            )}

            {/* ── 5. Campaign Health ── */}
            {data && data.campaigns.length > 0 && (
              <section>
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-headline-sm text-on-surface font-bold">Campaign Health</h2>
                  <Link
                    href="/campaigns"
                    className="text-sm font-medium text-on-surface-variant/50 hover:text-primary transition-colors"
                  >
                    View all
                  </Link>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {data.campaigns.slice(0, 4).map((c) => (
                    <CampaignHealthCard key={c.id} campaign={c} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ─── Sub-components ─── */

function KpiCard({ icon, label, value, sub }: { icon: string; label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl bg-surface-lowest/30 p-5 transition-all duration-200 hover:bg-surface-lowest/50 hover:-translate-y-0.5">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-md bg-primary/8 flex items-center justify-center">
          <Icon name={icon} className="text-xs text-primary" />
        </div>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant/50">{label}</span>
      </div>
      <p className="text-2xl font-bold text-on-surface leading-none mb-0.5">{value}</p>
      <p className="text-[11px] text-on-surface-variant/40">{sub}</p>
    </div>
  );
}

function NeedAttentionCard({ item, index }: { item: { type: string; label: string; action: string; campaign_id: string | null; campaign_name: string | null }; index: number }) {
  const actionHref = item.action === "review" ? "/draft" : "/campaigns";
  const actionLabelMap: Record<string, string> = { review: "Review", launch: "Launch" };

  return (
    <Link
      href={actionHref}
      className="block rounded-xl bg-error/8 p-4 transition-all duration-200 hover:bg-error/12 hover:-translate-y-0.5 active:scale-[0.98]"
      style={{ animationDelay: `${index * 0.06}s` }}
    >
      <div className="flex items-start gap-3">
        <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-error" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-error leading-snug">{item.label}</p>
          <p className="text-xs mt-1 font-semibold uppercase tracking-wider text-error/60">
            {actionLabelMap[item.action] || item.action}
          </p>
        </div>
        <Icon name="chevron_right" className="text-sm text-error/40 shrink-0 mt-1" />
      </div>
    </Link>
  );
}

function JobCard({ job }: { job: Record<string, unknown> }) {
  const progress = (job.progress as number) || 0;
  const stage = (job.stage as string) || "";
  const jobType = (job.type as string) || "";
  const label = JOB_TYPE_LABELS[jobType] || `Running ${jobType}`;
  const status = (job.status as string) || "";

  return (
    <div className="rounded-xl bg-surface-lowest/30 p-4 transition-all duration-200 hover:bg-surface-lowest/50">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse shrink-0" />
          <span className="text-sm text-on-surface font-semibold truncate">{label}</span>
        </div>
        <span className="text-xs font-semibold text-on-surface-variant/40 shrink-0 ml-2">{progress}%</span>
      </div>
      {stage && (
        <p className="text-xs text-on-surface-variant/50 mb-2.5 truncate">{stage}</p>
      )}
      <div className="w-full h-1 bg-surface-high/25 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-primary to-secondary transition-all duration-1000 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      {status === "queued" && (
        <p className="text-[11px] text-on-surface-variant/40 mt-1.5">Waiting in queue</p>
      )}
    </div>
  );
}

function effortEstimate(campaign: { status: string; pending_drafts: number; approved_drafts: number; lead_count: number }): string {
  switch (campaign.status) {
    case "ready_to_send":
      return "~Ready now";
    case "draft_review": {
      const n = campaign.pending_drafts;
      if (n <= 3) return `~${n} review${n > 1 ? "s" : ""} left`;
      return `${n} approvals needed`;
    }
    case "planning":
      return campaign.lead_count > 0 ? "~2 min" : "~10 min";
    case "generating":
      return "In progress";
    case "ready":
      return "~1 min";
    case "completed":
      return "Done";
    default:
      return "";
  }
}

function ContinueCard({ campaign, index }: { campaign: { id: string; name: string; status: string; lead_count: number; pending_drafts: number; approved_drafts: number; updated_at: string }; index: number }) {
  const progress = campaignProgress(campaign.status);
  const stage = STATUS_STAGE[campaign.status] || 0;
  const step = nextStep(campaign.status);
  const ready = isReady(campaign.status);
  const effort = effortEstimate(campaign);

  const actionHref = campaign.status === "draft_review" ? `/draft?campaign=${campaign.id}` : `/campaigns/${campaign.id}`;

  return (
    <Link
      href={actionHref}
      className="block rounded-xl bg-surface-lowest/30 p-5 transition-all duration-200 hover:bg-surface-lowest/50 hover:-translate-y-0.5 active:scale-[0.99]"
      style={{ animationDelay: `${index * 0.05}s` }}
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="text-body-md text-on-surface font-bold truncate">{campaign.name}</h3>
          <div className="flex items-center gap-2 mt-1.5">
            <span className={`text-[11px] font-semibold ${ready ? "text-success" : "text-on-surface-variant/50"}`}>
              {ready ? "Ready immediately" : "In progress"}
            </span>
            {effort && (
              <span className="text-[11px] text-on-surface-variant/40 bg-surface-high/15 rounded-full px-2 py-0.5">
                {effort}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-sm font-semibold text-primary shrink-0 ml-4 mt-0.5">
          Continue
          <Icon name="chevron_right" className="text-sm" />
        </div>
      </div>
      <div className="mt-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant/40">Next Step</p>
        <p className="text-sm font-medium text-on-surface mt-0.5">{step}</p>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div className="flex-1 h-1 bg-surface-high/25 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-primary to-secondary transition-all duration-1000 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-[10px] font-semibold text-on-surface-variant/30">{progress}%</span>
      </div>
    </Link>
  );
}

function RecommendationCard({ rec, index }: { rec: { type: string; observation: string; reason: string; action: string; confidence: string; link: string; why_details?: string[] }; index: number }) {
  const confidenceColor = rec.confidence === "high" ? "text-success" : rec.confidence === "medium" ? "text-warning" : "text-on-surface-variant/40";
  const [showWhy, setShowWhy] = useState(false);

  return (
    <div
      className="rounded-xl bg-surface-lowest/30 p-5 transition-all duration-200 hover:bg-surface-lowest/50 hover:-translate-y-0.5"
      style={{ animationDelay: `${index * 0.08}s` }}
    >
      <div className="flex items-start gap-3">
        <div className="w-7 h-7 rounded-lg bg-primary-container/10 flex items-center justify-center text-primary shrink-0 mt-0.5">
          <Icon name="auto_awesome" className="text-xs" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-sm font-medium text-on-surface leading-snug">{rec.observation}</p>
            <span className={`text-[10px] font-semibold uppercase ${confidenceColor}`}>{rec.confidence}</span>
          </div>
          {rec.reason && (
            <p className="text-xs text-on-surface-variant/60 leading-relaxed">{rec.reason}</p>
          )}
          <div className="flex items-center gap-3 mt-2">
            <Link
              href={rec.link}
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
            >
              {rec.action}
              <Icon name="chevron_right" className="text-xs" />
            </Link>
            {rec.why_details && rec.why_details.length > 0 && (
              <button
                onClick={(e) => { e.preventDefault(); setShowWhy(!showWhy); }}
                className="inline-flex items-center gap-1 text-xs text-on-surface-variant/40 hover:text-on-surface-variant/70 transition-colors"
              >
                <Icon name={showWhy ? "expand_less" : "help_outline"} className="text-xs" />
                {showWhy ? "Hide why" : "Why?"}
              </button>
            )}
          </div>
          {showWhy && rec.why_details && rec.why_details.length > 0 && (
            <div className="mt-3 pt-3 border-t border-surface-high/20">
              {rec.why_details.map((d, i) => (
                <div key={i} className="flex items-center gap-2 py-0.5">
                  <Icon name="check_circle" className="text-[10px] text-success shrink-0" />
                  <span className="text-xs text-on-surface-variant/60">{d}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ActivityRow({ item, index }: { item: { type: string; text: string; timestamp: string; count?: number; grouped?: boolean }; index: number }) {
  const iconMap: Record<string, string> = {
    campaign_completed: "check_circle",
    drafts_generated: "edit_note",
    campaign_ready: "rocket_launch",
    launch_ready: "rocket_launch",
    campaign_created: "add_circle",
    drafts_pending: "edit_note",
    drafts_approved: "task_alt",
    draft_approved: "task_alt",
  };
  const colorMap: Record<string, string> = {
    campaign_completed: "text-success",
    drafts_generated: "text-secondary",
    campaign_ready: "text-primary",
    launch_ready: "text-primary",
    campaign_created: "text-primary",
    drafts_pending: "text-warning",
    drafts_approved: "text-success",
    draft_approved: "text-success",
  };
  return (
    <div
      className="flex items-center gap-3 py-3 transition-all duration-200 hover:bg-surface-high/10 rounded-lg px-3 -mx-3"
      style={{ animationDelay: `${index * 0.04}s` }}
    >
      <div className={`w-7 h-7 rounded-lg bg-surface-high/30 flex items-center justify-center shrink-0 ${colorMap[item.type] || "text-on-surface-variant"}`}>
        <Icon name={iconMap[item.type] || "circle"} className="text-xs" />
      </div>
      <div className="flex-1 min-w-0 flex items-center gap-3">
        <p className="text-sm text-on-surface leading-snug flex-1 min-w-0">{item.text}</p>
        {item.grouped && item.count && item.count > 1 && (
          <span className="text-[10px] font-bold text-on-surface-variant/30 bg-surface-high/20 rounded-full px-2 py-0.5 shrink-0">
            {item.count}
          </span>
        )}
        <p className="text-[11px] text-on-surface-variant/35 shrink-0 tabular-nums">{shortTime(item.timestamp)}</p>
      </div>
    </div>
  );
}

function CampaignHealthCard({ campaign }: { campaign: { id: string; name: string; status: string; lead_count: number; pending_drafts: number; approved_drafts: number; updated_at: string } }) {
  const stage = campaignStage(campaign.status);
  const progress = campaignProgress(campaign.status);

  return (
    <Link
      href={`/campaigns/${campaign.id}`}
      className="block rounded-xl bg-surface-lowest/30 p-5 transition-all duration-200 hover:bg-surface-lowest/50 hover:-translate-y-0.5 active:scale-[0.99]"
    >
      <h3 className="text-body-md text-on-surface font-bold truncate mb-4">{campaign.name}</h3>
      <div className="flex items-center gap-0 mb-4">
        {STAGE_LABELS.map((label, i) => {
          const done = i < stage - 1;
          const current = i === stage - 1;
          return (
            <div key={label} className="flex items-center flex-1">
              <div className="flex flex-col items-center gap-1.5">
                <div className={`w-2.5 h-2.5 rounded-full transition-all duration-500 ${
                  done ? "bg-success" : current ? "bg-primary" : "bg-surface-high/25"
                }`} />
                <span className={`text-[10px] whitespace-nowrap ${
                  done ? "text-success font-medium" : current ? "text-primary font-semibold" : "text-on-surface-variant/30"
                }`}>
                  {current ? "Now" : label}
                </span>
              </div>
              {i < STAGE_LABELS.length - 1 && (
                <div className={`flex-1 h-px mx-1.5 mt-[-1.25rem] transition-all duration-500 ${
                  done ? "bg-success/40" : current ? "bg-primary/30" : "bg-surface-high/15"
                }`} />
              )}
            </div>
          );
        })}
      </div>
      <div className="w-full h-1 bg-surface-high/25 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-primary to-secondary transition-all duration-1000 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
    </Link>
  );
}
