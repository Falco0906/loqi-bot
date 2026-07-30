import {
  getMissionControl,
  getCampaign,
  listCampaigns,
} from "./api";
import type { MCSummary } from "./api";
import type {
  MCData,
  MCTask,
  MCRecommendation,
  MCLiveActivity,
  MCInsight,
  DiscoveryData,
  DiscoveryRecommendation,
  CampaignData,
  InboxData,
  InboxDecision,
  InboxAutoAction,
  InboxInsight,
  KnowledgeData,
  KnowledgeCard,
  KnowledgeTimelineEntry,
  KnowledgeEvolutionEntry,
  KnowledgeField,
  StrategicData,
  StrategicAdjustment,
  StrategicImpact,
  CampaignMilestone,
  CampaignImprovement,
  CampaignTimelineEntry,
  CampaignInsight,
  DiscoveryFilter,
  DiscoveryAlsoConsidered,
} from "./domain";

/* ─── Utilities ─── */

function getToken(): string | null {
  try {
    return localStorage.getItem("loqi_active_session_token");
  } catch {
    return null;
  }
}

/* ─── Mission Control ─── */

function mcBriefFromBackend(brief: MCSummary["brief"]): MCData["brief"] {
  return {
    greeting: brief.greeting,
    lines: brief.lines,
    suggestion: brief.suggestion,
  };
}

function mcTasksFromBackend(data: MCSummary): MCTask[] {
  const tasks: MCTask[] = [];
  for (const item of data.needs_attention) {
    tasks.push({
      id: `attention-${item.campaign_id ?? item.label}`,
      title: item.label,
      completed: false,
    });
  }
  return tasks;
}

function mcRecommendationsFromBackend(data: MCSummary): MCRecommendation[] {
  return data.recommendations.map((r) => ({
    type: r.type,
    observation: r.observation,
    reason: r.reason,
    action: r.action,
    confidence: r.confidence,
    link: r.link,
    why_details: r.why_details,
  }));
}

function mcActivityFromBackend(data: MCSummary): MCLiveActivity[] {
  return data.live_activity.map((a) => ({
    type: a.type,
    text: a.text,
    timestamp: a.timestamp,
    count: a.count,
    grouped: a.grouped,
  }));
}

function mcInsightsFromBackend(_data: MCSummary): MCInsight[] {
  return [];
}

export async function fetchMissionControl(): Promise<MCData | null> {
  const token = getToken();
  if (!token) return null;
  const raw = await getMissionControl(token);
  if (!raw.ok) return null;
  return {
    brief: mcBriefFromBackend(raw.brief),
    tasks: mcTasksFromBackend(raw),
    recommendations: mcRecommendationsFromBackend(raw),
    liveActivity: mcActivityFromBackend(raw),
    insights: mcInsightsFromBackend(raw),
    activeJobLabel: null,
    activeJobProgress: null,
    activeJobTotal: null,
  };
}

/* ─── Discovery ─── */

// TODO: Replace with real backend endpoint when the discovery workspace API is built
export async function fetchDiscovery(): Promise<DiscoveryData | null> {
  const _token = getToken();
  return null;
}

/* ─── Campaigns Detail ─── */

function campaignMilestonesFromBackend(campaign: Record<string, unknown>): CampaignMilestone[] {
  const raw = campaign.milestones;
  if (Array.isArray(raw)) return raw as CampaignMilestone[];
  return [];
}

function campaignImprovementsFromBackend(campaign: Record<string, unknown>): CampaignImprovement[] {
  const raw = campaign.improvements;
  if (Array.isArray(raw)) return raw as CampaignImprovement[];
  return [];
}

function campaignTimelineFromBackend(campaign: Record<string, unknown>): CampaignTimelineEntry[] {
  const raw = campaign.timeline;
  if (Array.isArray(raw)) return raw as CampaignTimelineEntry[];
  return [];
}

function campaignInsightsFromBackend(campaign: Record<string, unknown>): CampaignInsight[] {
  const raw = campaign.insights;
  if (Array.isArray(raw)) return raw as CampaignInsight[];
  return [];
}

export async function fetchCampaign(id: string): Promise<CampaignData | null> {
  const token = getToken();
  if (!token) return null;
  const raw = await getCampaign(token, id);
  if (!raw.ok || !raw.campaign) return null;
  const c = raw.campaign;
  return {
    name: (c.name as string) || "Untitled Campaign",
    status: (c.status as string) || "planning",
    createdAt: (c.created_at as string) || "",
    objective: (c.objective as string) || "",
    milestones: campaignMilestonesFromBackend(c),
    improvements: campaignImprovementsFromBackend(c),
    timeline: campaignTimelineFromBackend(c),
    insights: campaignInsightsFromBackend(c),
    recommendation: {
      title: ((c.recommendation as Record<string, unknown>)?.title as string) || "",
      body: ((c.recommendation as Record<string, unknown>)?.body as string) || "",
    },
  };
}

export async function fetchCampaignList() {
  const token = getToken();
  if (!token) return null;
  return listCampaigns(token);
}

/* ─── Inbox ─── */

// TODO: Replace with real backend endpoint when the inbox workspace API is built
export async function fetchInbox(): Promise<InboxData | null> {
  const _token = getToken();
  return null;
}

/* ─── Knowledge ─── */

// TODO: Replace with real backend endpoint when the knowledge workspace API is built
export async function fetchKnowledge(): Promise<KnowledgeData | null> {
  const _token = getToken();
  return null;
}

/* ─── Strategic Update ─── */

// TODO: Replace with real backend endpoint when the strategic update workspace API is built
export async function fetchStrategicUpdate(): Promise<StrategicData | null> {
  const _token = getToken();
  return null;
}
