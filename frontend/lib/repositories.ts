import {
  getMissionControl,
  getBriefing,
  getCampaign,
  listCampaigns,
  listConversations,
  listDiscoveries,
  getDiscovery,
  startDiscoveryJob,
} from "./api";
import type { MCSummary, BriefingResponse } from "./api";
import { getStrategicProfile } from "./strategic-intelligence-api";
import type { StrategicProfile } from "./strategic-intelligence-api";
import type {
  MCData,
  MCTask,
  MCRecommendation,
  MCLiveActivity,
  MCInsight,
  MCBriefingData,
  MCIntentionCard,
  MCBriefing,
  MCHealthSummary,
  MCTimelineEvent,
  DiscoveryData,
  DiscoveryRecommendation,
  DiscoveryListItem,
  DiscoveryStatus,
  DiscoveryPlan,
  DiscoveryProgress,
  CampaignData,
  InboxData,
  InboxConversationRow,
  KnowledgeData,
  KnowledgeCard,
  KnowledgeTimelineEntry,
  KnowledgeEvolutionEntry,
  StrategicData,
  StrategicAdjustment,
  StrategicImpact,
  CampaignMilestone,
  CampaignImprovement,
  CampaignTimelineEntry,
  CampaignInsight,
} from "./domain";

// PR-3C/3D: re-export payload types for pages consuming cached fetchers.
export type { InboxData, InboxConversationRow, CampaignData } from "./domain";
import { qualificationFromPersistedMetadata } from "./discovery-qualification";

/* ─── Utilities ─── */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordFromJson(value: unknown): Record<string, unknown> {
  if (isRecord(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      return isRecord(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }
  return {};
}

const CACHE_TTL_MS = 20_000;
const fetchCache = new Map<
  string,
  { promise: Promise<unknown>; ts: number; value: unknown }
>();

function memoizedFetch<T>(key: string, fn: () => Promise<T | null>): Promise<T | null> {
  const hit = fetchCache.get(key);
  if (hit && Date.now() - hit.ts < CACHE_TTL_MS) {
    return hit.promise as Promise<T | null>;
  }
  const promise = fn()
    .then((value) => {
      const entry = fetchCache.get(key);
      if (entry) entry.value = value;
      return value;
    })
    .catch((err: unknown) => {
      fetchCache.delete(key);
      throw err;
    });
  fetchCache.set(key, { promise, ts: Date.now(), value: undefined });
  return promise;
}

/**
 * Synchronous cache peek: returns the freshest resolved value for a key
 * without awaiting. Used to seed page state so destinations render
 * instantly after Copilot navigation (no skeleton flash on arrival).
 */
function peekCached<T>(name: string): T | null {
  const hit = fetchCache.get(sessionKey(name));
  if (!hit || Date.now() - hit.ts >= CACHE_TTL_MS) return null;
  return (hit.value as T | null | undefined) ?? null;
}

function sessionKey(name: string): string {
  let token = "";
  try {
    token = getToken() ?? "";
  } catch {
    /* noop */
  }
  return `${name}:${token}`;
}

export function prefetchBriefing(): Promise<MCBriefingData | null> {
  return memoizedFetch(sessionKey("briefing"), fetchBriefing);
}

export function prefetchMissionControl(): Promise<MCData | null> {
  return memoizedFetch(sessionKey("mission-control"), fetchMissionControl);
}

export function peekCachedMissionControl(): MCData | null {
  return peekCached<MCData>("mission-control");
}

export function peekCachedBriefing(): MCBriefingData | null {
  return peekCached<MCBriefingData>("briefing");
}

export function invalidateMissionControlCache(): void {
  fetchCache.delete(sessionKey("mission-control"));
}

export function profileFieldToString(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(profileFieldToString).join(", ");
  if (isRecord(value)) {
    return Object.entries(value)
      .map(([k, v]) => `${k}: ${profileFieldToString(v)}`)
      .join("; ");
  }
  if (value == null) return "";
  return String(value);
}

function getToken(): string | null {
  try {
    return localStorage.getItem("loqi_active_session_token");
  } catch {
    return null;
  }
}

function getUserId(): string | null {
  try {
    return localStorage.getItem("loqi_user_id");
  } catch {
    return null;
  }
}

function toRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(value)) {
    const n = Number(v);
    out[k] = Number.isFinite(n) ? n : 0;
  }
  return out;
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

function mcInsightsFromBackend(data: MCSummary): MCInsight[] {
  const insights: MCInsight[] = [];
  const analysis = data.workspace_analysis;

  const cross = analysis?.cross_campaign_insights ?? [];
  for (const item of cross) {
    const text = typeof item.insight === "string" ? item.insight : "";
    if (!text) continue;
    const insightType = typeof item.insight_type === "string" ? item.insight_type : "";
    const icon =
      insightType === "ready"
        ? "rocket_launch"
        : insightType === "review_backlog"
          ? "rate_review"
          : insightType === "idle"
            ? "hourglass_empty"
            : "lightbulb";
    insights.push({ icon, text });
  }

  const focus = analysis?.current_focus;
  if (focus && typeof focus.focus === "string" && focus.focus) {
    insights.push({ icon: "center_focus_strong", text: focus.focus });
  }

  const health = analysis?.workspace_health;
  if (health && typeof health.overall_health === "string" && health.overall_health) {
    const velocity =
      typeof health.pipeline_velocity === "string"
        ? health.pipeline_velocity.replace(/_/g, " ")
        : "";
    insights.push({
      icon: "monitoring",
      text: velocity
        ? `Workspace health: ${health.overall_health}. Pipeline ${velocity}.`
        : `Workspace health: ${health.overall_health}.`,
    });
  }

  return insights;
}

function mcActiveJobFromBackend(data: MCSummary): {
  activeJobLabel: string | null;
  activeJobProgress: number | null;
  activeJobTotal: number | null;
  initialResearchStatus: string | null;
  initialResearchError: string | null;
  initialResearchResultCount: number | null;
} {
  const jobs = Array.isArray(data.active_jobs) ? data.active_jobs : [];
  const first = jobs[0] as Record<string, unknown> | undefined;
  if (!first) {
    const initial = data.initial_research;
    return {
      activeJobLabel: initial && typeof initial.stage === "string" ? initial.stage : null,
      activeJobProgress: initial && typeof initial.progress === "number" ? initial.progress : null,
      activeJobTotal: initial ? 100 : null,
      initialResearchStatus: initial && typeof initial.status === "string" ? initial.status : null,
      initialResearchError: initial && typeof initial.error_message === "string" ? initial.error_message : null,
      initialResearchResultCount: typeof data.initial_research_result_count === "number"
        ? data.initial_research_result_count
        : null,
    };
  }

  const query = typeof first.query === "string" ? first.query : "";
  const stage = typeof first.stage === "string" ? first.stage : "";
  const type = typeof first.type === "string" ? first.type : "job";
  const progress =
    typeof first.progress === "number"
      ? first.progress
      : typeof first.progress === "string"
        ? Number(first.progress) || 0
        : 0;

  const label = stage
    ? stage
    : query
      ? `${type}: ${query}`
      : `Running ${type}`;

  return {
    activeJobLabel: label,
    activeJobProgress: Math.min(100, Math.max(0, progress)),
    activeJobTotal: 100,
    initialResearchStatus: "running",
    initialResearchError: null,
    initialResearchResultCount: null,
  };
}

export async function fetchMissionControl(): Promise<MCData | null> {
  return memoizedFetch(sessionKey("mission-control"), async () => {
    const token = getToken();
    if (!token) return null;
    const raw = await getMissionControl(token, getUserId() ?? "");
    if (!raw.ok) return null;
    const job = mcActiveJobFromBackend(raw);
    return {
      brief: mcBriefFromBackend(raw.brief),
      tasks: mcTasksFromBackend(raw),
      recommendations: mcRecommendationsFromBackend(raw),
      liveActivity: mcActivityFromBackend(raw),
      insights: mcInsightsFromBackend(raw),
      activeJobLabel: job.activeJobLabel,
      activeJobProgress: job.activeJobProgress,
      activeJobTotal: job.activeJobTotal,
      initialResearchStatus: job.initialResearchStatus,
      initialResearchError: job.initialResearchError,
      initialResearchResultCount: job.initialResearchResultCount,
    };
  });
}

/* ─── Phase 11: Briefing ─── */

function briefingFromBackend(raw: BriefingResponse): MCBriefing {
  return {
    greeting: raw.briefing.greeting,
    lines: raw.briefing.lines,
    suggestion: raw.briefing.suggestion,
    overallSummary: raw.briefing.overall_summary,
    primaryFocus: raw.briefing.primary_focus,
    topRecommendation: raw.briefing.top_recommendation,
  };
}

function intentionCardsFromBackend(cards: BriefingResponse["top_priorities"]): MCIntentionCard[] {
  return cards.map((c) => ({
    id: c.id,
    title: c.title,
    summary: c.summary,
    priority: c.priority as MCIntentionCard["priority"],
    confidence: c.confidence,
    evidence: c.evidence,
    recommendedAction: c.recommended_action,
    relatedCampaign: c.related_campaign,
    relatedLead: c.related_lead,
    reasonCode: c.reason_code,
  }));
}

function healthFromBackend(h: BriefingResponse["workspace_health"]): MCHealthSummary {
  return {
    overallHealth: h.overall_health,
    pipelineVelocity: h.pipeline_velocity,
    bottlenecks: h.bottlenecks,
    providerHealth: h.provider_health,
    confidenceScore: h.confidence_score,
    campaignsReady: h.campaigns_ready,
    campaignsWaiting: h.campaigns_waiting,
    draftBacklog: h.draft_backlog,
    details: h.details,
  };
}

function timelineFromBackend(events: BriefingResponse["timeline"]): MCTimelineEvent[] {
  return events.map((e) => ({
    id: e.id,
    timestamp: e.timestamp,
    type: e.type,
    description: e.description,
    category: e.category,
    actor: e.actor,
  }));
}

export async function fetchBriefing(): Promise<MCBriefingData | null> {
  return memoizedFetch(sessionKey("briefing"), async () => {
    const token = getToken();
    if (!token) return null;
    const raw = await getBriefing(token, getUserId() ?? "");
    if (!raw.ok) return null;
    return {
      briefing: briefingFromBackend(raw),
      topPriorities: intentionCardsFromBackend(raw.top_priorities),
      waitingOnYou: intentionCardsFromBackend(raw.waiting_on_you),
      loqiHandled: intentionCardsFromBackend(raw.loqi_handled),
      upcoming: intentionCardsFromBackend(raw.upcoming),
      workspaceHealth: healthFromBackend(raw.workspace_health),
      timeline: timelineFromBackend(raw.timeline),
    };
  });
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
    id: (c.id as string) || id,
    name: (c.name as string) || "Untitled Campaign",
    status: (c.status as string) || "planning",
    currentStep: (c.current_step as string) || "",
    generation:
      typeof c.generation === "object" && c.generation !== null
        ? (c.generation as { status?: string; total?: number; completed?: number; batch_id?: string })
        : undefined,
    createdAt: (c.created_at as string) || "",
    objective: (c.objective as string) || "",
    discoveryId: String((c.discovery_id as string) || ""),
    leadCount: Number(c.lead_count || 0),
    pendingDrafts: Number(c.pending_drafts || 0),
    approvedDrafts: Number(c.approved_drafts || 0),
    launch:
      isRecord(c.launch) || typeof c.launch === "object"
        ? {
            status: String(((c.launch as Record<string, unknown>).status as string) || ""),
            total: Number(((c.launch as Record<string, unknown>).total as number) || 0),
            sent: Number(((c.launch as Record<string, unknown>).sent as number) || 0),
            failed: Number(((c.launch as Record<string, unknown>).failed as number) || 0),
          }
        : undefined,
    leads: Array.isArray(c.leads) ? c.leads as Array<Record<string, unknown>> : [],
    strategy: (c.strategy as Record<string, unknown>) || null,
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

/**
 * The contact is the participant with role "contact". Senders (the agent's own
 * outbound addresses) are role "sender" and come first in participants, so
 * picking participants[0] would surface the agent instead of the contact.
 */
function contactFromConversation(
  c: Record<string, unknown>,
): Record<string, unknown> {
  const participants = Array.isArray(c.participants)
    ? (c.participants as Record<string, unknown>[])
    : [];
  const byRole = participants.find(
    (p) => String(p.role || "").toLowerCase() === "contact",
  );
  return byRole || participants[1] || participants[0] || {};
}

function inboxRowFromConversation(c: Record<string, unknown>): InboxConversationRow {
  const contact = contactFromConversation(c);
  const summary = (c.summary as Record<string, unknown>) || {};
  const metadata = (c.metadata as Record<string, unknown>) || {};
  return {
    id: String(c.conversation_id || c.id || ""),
    name: String(
      contact.name || contact.email || summary.contact_name || "Contact",
    ),
    email: String(contact.email || summary.contact_email || ""),
    company: String(
      c.company_name || summary.company || contact.company || "",
    ),
    status: String(c.status || "unknown"),
    classification: String(metadata.last_reply_category || ""),
    interest: String(summary.interest_level || ""),
    preview: String(c.last_message_preview || ""),
    lastActivityAt: String(c.last_activity_at || c.updated_at || ""),
    messageCount: Number(c.message_count || 0),
  };
}

export async function fetchInbox(): Promise<InboxData | null> {
  const token = getToken();
  if (!token) return null;
  const raw = await listConversations(token);
  const conversations = Array.isArray(raw.conversations)
    ? raw.conversations
    : [];
  const rows = conversations.map((c) =>
    inboxRowFromConversation(c as Record<string, unknown>),
  );

  return { rows };
}

/* ─── Knowledge ─── */

function confidenceMode(level: string | undefined): KnowledgeCard["confidenceMode"] {
  const v = (level || "").toLowerCase();
  if (v === "high") return "high";
  if (v === "low") return "low";
  if (v === "learning") return "learning";
  return "medium";
}

function confidenceLabel(level: string | undefined): string {
  const mode = confidenceMode(level);
  if (mode === "high") return "High confidence";
  if (mode === "low") return "Low confidence";
  if (mode === "learning") return "Still learning";
  return "Medium confidence";
}

function knowledgeCardsFromProfile(profile: StrategicProfile): KnowledgeCard[] {
  const levels = profile.CONFIDENCE_LEVELS || {};
  const cards: KnowledgeCard[] = [];

  if (profile.COMPANY_SUMMARY || profile.INDUSTRY || profile.PRODUCT) {
    cards.push({
      id: "company",
      category: "Company",
      title: "Market Position",
      confidence: confidenceLabel(levels.COMPANY_SUMMARY || levels.overall),
      confidenceMode: confidenceMode(levels.COMPANY_SUMMARY || levels.overall),
      fields: [
        ...(profile.COMPANY_SUMMARY
          ? [{ label: "Summary", value: profile.COMPANY_SUMMARY }]
          : []),
        ...(profile.INDUSTRY ? [{ label: "Industry", value: profile.INDUSTRY }] : []),
        ...(profile.BUSINESS_MODEL
          ? [{ label: "Business model", value: profile.BUSINESS_MODEL }]
          : []),
        ...(profile.PRODUCT ? [{ label: "Product", value: profile.PRODUCT }] : []),
      ],
    });
  }

  if (profile.ICP) {
    cards.push({
      id: "icp",
      category: "Audience",
      title: "Ideal Customer",
      confidence: confidenceLabel(levels.ICP || levels.overall),
      confidenceMode: confidenceMode(levels.ICP || levels.overall),
      fields: [{ label: "ICP", value: profile.ICP }],
    });
  }

  if (Array.isArray(profile.BUYER_PERSONAS) && profile.BUYER_PERSONAS.length > 0) {
    cards.push({
      id: "personas",
      category: "Audience",
      title: "Buyer Personas",
      confidence: confidenceLabel(levels.BUYER_PERSONAS || levels.overall),
      confidenceMode: confidenceMode(levels.BUYER_PERSONAS || levels.overall),
      fields: profile.BUYER_PERSONAS.slice(0, 3).map((p) => ({
        label: p.title || p.name || "Persona",
        value: [p.motivation, p.objections].filter(Boolean).join(" — ") || p.name,
      })),
    });
  }

  if (profile.DIFFERENTIATION || profile.MARKET_POSITION || profile.COMPETITIVE_LANDSCAPE) {
    cards.push({
      id: "positioning",
      category: "Positioning",
      title: "Competitive Edge",
      confidence: confidenceLabel(levels.DIFFERENTIATION || levels.overall),
      confidenceMode: confidenceMode(levels.DIFFERENTIATION || levels.overall),
      fields: [
        ...(profile.DIFFERENTIATION
          ? [{ label: "Differentiation", value: profile.DIFFERENTIATION }]
          : []),
        ...(profile.MARKET_POSITION
          ? [{ label: "Market position", value: profile.MARKET_POSITION }]
          : []),
        ...(profile.COMPETITIVE_LANDSCAPE
          ? [{ label: "Landscape", value: profile.COMPETITIVE_LANDSCAPE }]
          : []),
      ],
    });
  }

  if (profile.PRIMARY_OBJECTIVE || profile.CURRENT_CONSTRAINTS) {
    cards.push({
      id: "objectives",
      category: "Strategy",
      title: "Objectives & Constraints",
      confidence: confidenceLabel(levels.PRIMARY_OBJECTIVE || levels.overall),
      confidenceMode: confidenceMode(levels.PRIMARY_OBJECTIVE || levels.overall),
      fields: [
        ...(profile.PRIMARY_OBJECTIVE
          ? [{ label: "Primary objective", value: profile.PRIMARY_OBJECTIVE }]
          : []),
        ...(profile.CURRENT_CONSTRAINTS
          ? [{ label: "Current constraints", value: profile.CURRENT_CONSTRAINTS }]
          : []),
      ],
    });
  }

  if (profile.MESSAGING) {
    cards.push({
      id: "messaging",
      category: "Messaging",
      title: "Value Proposition",
      confidence: confidenceLabel(levels.MESSAGING || levels.overall),
      confidenceMode: confidenceMode(levels.MESSAGING || levels.overall),
      fields: [{ label: "Recommended messaging", value: profile.MESSAGING, variant: "quote" }],
    });
  }

  if (Array.isArray(profile.RISKS) && profile.RISKS.length > 0) {
    cards.push({
      id: "risks",
      category: "Risk",
      title: "Strategic Risks",
      confidence: confidenceLabel(levels.RISKS || levels.overall),
      confidenceMode: confidenceMode(levels.RISKS || levels.overall),
      fields: [
        {
          label: "Risks",
          value: "",
          variant: "tags",
          tags: profile.RISKS.map(String),
        },
      ],
    });
  }

  if (Array.isArray(profile.KNOWN_UNKNOWNS) && profile.KNOWN_UNKNOWNS.length > 0) {
    cards.push({
      id: "unknowns",
      category: "Learning",
      title: "Known Unknowns",
      confidence: "Still learning",
      confidenceMode: "learning",
      fields: [
        {
          label: "Gaps",
          value: "",
          variant: "tags",
          tags: profile.KNOWN_UNKNOWNS.map(String),
        },
      ],
    });
  }

  return cards;
}

function knowledgeMemoryTimeline(
  memory: Record<string, unknown>,
): { timeline: KnowledgeTimelineEntry[]; evolution: KnowledgeEvolutionEntry[] } {
  const timeline: KnowledgeTimelineEntry[] = [];
  const evolution: KnowledgeEvolutionEntry[] = [];

  if (typeof memory.last_search === "string" && memory.last_search) {
    timeline.push({
      time: "Recent",
      event: `Last research: ${memory.last_search}`,
      highlight: true,
    });
    evolution.push({ label: "Research memory updated" });
  }
  if (typeof memory.last_campaign_name === "string" && memory.last_campaign_name) {
    timeline.push({
      time: "Recent",
      event: `Opened campaign: ${memory.last_campaign_name}`,
      highlight: false,
    });
    evolution.push({ label: "Campaign focus remembered" });
  }
  if (typeof memory.last_action === "string" && memory.last_action) {
    timeline.push({
      time: "Recent",
      event: `Last action: ${memory.last_action}`,
      highlight: false,
    });
  }

  return { timeline, evolution };
}

export async function fetchKnowledge(): Promise<KnowledgeData | null> {
  const userId = getUserId();
  if (!userId) return null;

  try {
    const { profile, generated_at } = await getStrategicProfile(userId);
    if (!profile) return null;

    const cards = knowledgeCardsFromProfile(profile);
    if (cards.length === 0) return null;

    let timeline: KnowledgeTimelineEntry[] = [];
    let evolution: KnowledgeEvolutionEntry[] = [];
    const token = getToken();
    if (token) {
      try {
        const mc = await getMissionControl(token);
        if (mc.ok && mc.workspace_memory) {
          const derived = knowledgeMemoryTimeline(mc.workspace_memory);
          timeline = derived.timeline;
          evolution = derived.evolution;
        }
      } catch {
        /* memory is optional */
      }
    }

    return {
      cards,
      timeline,
      evolution,
      lastSync: generated_at
        ? `Synced ${new Date(generated_at).toLocaleString()}`
        : "Synced from strategic profile",
      brainVersion: "Strategic Profile v1",
    };
  } catch {
    return null;
  }
}

/* ─── Strategic Update ─── */

function strategicDataFromProfile(profile: StrategicProfile): StrategicData {
  const adjustments: StrategicAdjustment[] = [];

  if (profile.CURRENT_CONSTRAINTS) {
    adjustments.push({
      area: "CONSTRAINTS",
      icon: "warning",
      title: "Current Constraint",
      description: profileFieldToString(profile.CURRENT_CONSTRAINTS),
      colSpan: true,
    });
  }
  if (Array.isArray(profile.GROWTH_OPPORTUNITIES)) {
    for (const opp of profile.GROWTH_OPPORTUNITIES.slice(0, 2)) {
      adjustments.push({
        area: "GROWTH",
        icon: "trending_up",
        title: "Growth Opportunity",
        description: profileFieldToString(opp),
        colSpan: false,
      });
    }
  }
  if (Array.isArray(profile.RISKS) && profile.RISKS[0]) {
    adjustments.push({
      area: "RISK",
      icon: "shield",
      title: "Strategic Risk",
      description: profileFieldToString(profile.RISKS[0]),
      colSpan: false,
    });
  }
  if (profile.DIFFERENTIATION) {
    adjustments.push({
      area: "POSITIONING",
      icon: "explore",
      title: "Differentiation",
      description: profileFieldToString(profile.DIFFERENTIATION),
      colSpan: false,
    });
  }

  const impacts: StrategicImpact[] = [];
  if (profile.PRIMARY_OBJECTIVE) {
    impacts.push({
      label: "Primary objective",
      value: profileFieldToString(profile.PRIMARY_OBJECTIVE),
      severity: "high",
    });
  }
  if (profile.CURRENT_CONSTRAINTS) {
    impacts.push({
      label: "Blocking constraint",
      value: profileFieldToString(profile.CURRENT_CONSTRAINTS),
      severity: "high",
    });
  }
  if (profile.MARKET_POSITION) {
    impacts.push({
      label: "Market position",
      value: profileFieldToString(profile.MARKET_POSITION),
      severity: "medium",
    });
  }

  const overall = (profile.CONFIDENCE_LEVELS?.overall || "medium").toLowerCase();
  const phaseProgress = overall === "high" ? 75 : overall === "low" ? 35 : 55;

  return {
    subtitle: profile.INDUSTRY
      ? `Based on your ${profileFieldToString(profile.INDUSTRY)} strategic profile`
      : "Based on your current strategic profile",
    understanding: profileFieldToString(profile.COMPANY_SUMMARY || profile.PRODUCT || "Strategic profile established"),
    adjustments,
    impacts,
    recommendation: profileFieldToString(
      profile.MESSAGING ||
      profile.PRIMARY_OBJECTIVE ||
      "Continue executing against the current strategic profile.",
    ),
    phaseLabel: overall === "high" ? "High confidence" : overall === "low" ? "Building confidence" : "Steady phase",
    phaseProgress,
    stableContinuity: [
      ...(profile.ICP ? ["Ideal customer profile remains the research north star"] : []),
      ...(profile.PRODUCT ? ["Core product definition stays consistent"] : []),
    ],
    affectedAreas: [
      ...(profile.MESSAGING ? ["Messaging"] : []),
      ...(profile.ICP ? ["Discovery targeting"] : []),
      ...(profile.PRIMARY_OBJECTIVE ? ["Campaign objectives"] : []),
    ],
  };
}

export async function fetchStrategicUpdate(): Promise<StrategicData | null> {
  const userId = getUserId();
  if (!userId) return null;
  try {
    const { profile } = await getStrategicProfile(userId);
    if (!profile) return null;
    return strategicDataFromProfile(profile);
  } catch {
    return null;
  }
}

/* ─── Discovery ─── */

function _scoreToMatch(value: unknown, fallback: number): number {
  if (typeof value === "number") return Math.round(value);
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : fallback;
}

function _companyToRecommendation(
  company: Record<string, unknown>,
  index: number,
  qualification?: DiscoveryRecommendation["qualification"],
): DiscoveryRecommendation {
  const stage = (company.stage as string) || "";
  const employeeCount = company.employee_count;
  const stageLabel = stage
    || (typeof employeeCount === "number" && employeeCount > 0
        ? `${employeeCount} employees`
        : "Prospect");
  return {
    id: String(company.id || `company-${index}`),
    company: String(company.name || company.domain || "Unknown company"),
    match: _scoreToMatch(company.match_score, Math.max(55, 90 - index * 3)),
    subtitle: String(company.industry || "Company"),
    stage: stageLabel,
    location: [company.city, company.country].filter(Boolean).join(", ") || "Unknown",
    reasoning: String(company.description || "Matched from research results."),
    buyingSignal: String(company.buying_signal || "Research match"),
    signalDetail: String(company.snippet || company.headline || ""),
    funding: String(company.funding || "—"),
    hiring: String(company.hiring || "—"),
    alsoConsidered: [],
    qualification,
  };
}

export function workspaceLeadToRecommendation(
  wl: Record<string, unknown>,
  index: number,
): DiscoveryRecommendation {
  const profile =
    (wl.lead as Record<string, unknown> | undefined)
    || (wl as Record<string, unknown>);
  const firstName = String(wl.first_name || profile.first_name || "");
  const lastName = String(wl.last_name || profile.last_name || "");
  const name = [firstName, lastName].filter(Boolean).join(" ");
  const title = String(wl.title || profile.title || "");
  const profileMetadata = recordFromJson(profile.metadata);
  const qualification: DiscoveryRecommendation["qualification"] | null =
    qualificationFromPersistedMetadata(wl.metadata) as DiscoveryRecommendation["qualification"] | null;
  return {
    id: String(wl.id || `lead-${index}`),
    company: String(
      profile.company_name
       || profileMetadata.company
      || name
      || "Unknown company",
    ),
    match: _scoreToMatch(wl.match_score, Math.max(55, 90 - index * 3)),
    subtitle: title || name || "Prospect",
    stage: String(profile.seniority || wl.lead_status || "Prospect"),
    location: String(
      profile.location
      || profile.city
      || wl.location
      || "Unknown",
    ),
    reasoning: [
      name && title ? `${name} (${title})` : name || title,
      wl.linkedin_url || profile.linkedin_url ? "LinkedIn profile available" : null,
      wl.email ? "Email on file" : null,
    ].filter(Boolean).join(". ") || "Matched from research results.",
    buyingSignal: String(profile.buying_signal || profile.signal || "Research match"),
    signalDetail: String(profile.buying_signal_detail || profile.snippet || profile.headline || ""),
    funding: String(profile.funding || "—"),
    hiring: String(profile.hiring || "—"),
    alsoConsidered: [],
    qualification: qualification || undefined,
  };
}

export async function fetchDiscoveryList(): Promise<DiscoveryListItem[] | null> {
  return memoizedFetch(sessionKey("discovery-list"), async () => {
    const token = getToken();
    if (!token) return null;
    try {
      const res = await listDiscoveries(token);
      const items = Array.isArray(res.discoveries) ? res.discoveries : [];
      return items.map((d) => ({
        id: String(d.id),
        query: String(d.query || ""),
        status: (d.status as DiscoveryStatus) || "queued",
        companyCount: Number(d.company_count) || 0,
        leadCount: Number(d.lead_count) || 0,
        createdAt: String(d.created_at || ""),
        completedAt: d.completed_at ? String(d.completed_at) : null,
        summary: d.summary || {},
        title: d.title ?? null,
        description: d.description ?? null,
        favorite: Boolean(d.favorite),
        archivedAt: d.archived_at ? String(d.archived_at) : null,
        lastViewedAt: d.last_viewed_at ? String(d.last_viewed_at) : null,
        lastRefreshedAt: d.last_refreshed_at ? String(d.last_refreshed_at) : null,
        metadata: d.metadata || {},
      }));
    } catch {
      return null;
    }
  });
}

export function prefetchDiscoveryList(): Promise<DiscoveryListItem[] | null> {
  return memoizedFetch(sessionKey("discovery-list"), fetchDiscoveryList);
}

export function peekCachedDiscoveryList(): DiscoveryListItem[] | null {
  return peekCached<DiscoveryListItem[]>("discovery-list");
}

export async function fetchDiscovery(id: string): Promise<DiscoveryData | null> {
  return memoizedFetch(sessionKey(`discovery:${id}`), async () => {
    const token = getToken();
    if (!token || !id) return null;
    try {
      const res = await getDiscovery(token, id);
      const d = res.discovery;
      if (!d) return null;

      const status = (d.status as DiscoveryStatus) || "queued";
      const companies = Array.isArray(d.discovery_companies) ? d.discovery_companies : [];
      const leads = Array.isArray(d.discovery_leads) ? d.discovery_leads : [];
      const providerCounts = toRecord(d.provider_provenance);
      const metadata = isRecord(d.metadata) ? d.metadata : {};
      const rawProgress = isRecord(metadata.progress) ? metadata.progress : {};
      const rawPlan = isRecord(metadata.plan) ? metadata.plan : {};
      const progress: DiscoveryProgress = {
        stage: typeof rawProgress.stage === "string" ? rawProgress.stage : "",
        progress:
          typeof rawProgress.progress === "number"
            ? rawProgress.progress
            : Number(rawProgress.progress) || 0,
      };
      const plan: DiscoveryPlan = {
        offering: String(rawPlan.offering || ""),
        primaryServices: Array.isArray(rawPlan.primary_services) ? rawPlan.primary_services.map(String) : [],
        targetAudience: String(rawPlan.target_audience || ""),
        industries: Array.isArray(rawPlan.industries) ? rawPlan.industries.map(String) : [],
        subIndustries: Array.isArray(rawPlan.sub_industries) ? rawPlan.sub_industries.map(String) : [],
        icpSummary: String(rawPlan.icp_summary || ""),
        buyerPersonas: Array.isArray(rawPlan.buyer_personas) ? rawPlan.buyer_personas.map(String) : [],
        companyKeywords: Array.isArray(rawPlan.company_keywords) ? rawPlan.company_keywords.map(String) : [],
        decisionMakerRoles: Array.isArray(rawPlan.decision_maker_roles) ? rawPlan.decision_maker_roles.map(String) : [],
        negativeKeywords: Array.isArray(rawPlan.negative_keywords) ? rawPlan.negative_keywords.map(String) : [],
        painPoints: Array.isArray(rawPlan.pain_points) ? rawPlan.pain_points.map(String) : [],
        buyingSignals: Array.isArray(rawPlan.buying_signals) ? rawPlan.buying_signals.map(String) : [],
        technologies: Array.isArray(rawPlan.technologies) ? rawPlan.technologies.map(String) : [],
        businessCharacteristics: Array.isArray(rawPlan.business_characteristics) ? rawPlan.business_characteristics.map(String) : [],
        exclusions: Array.isArray(rawPlan.exclusions) ? rawPlan.exclusions.map(String) : [],
        geography: Array.isArray(rawPlan.geography) ? rawPlan.geography.map(String) : [],
        companySize: Array.isArray(rawPlan.company_size) ? rawPlan.company_size.map(String) : [],
        messagingAngle: String(rawPlan.messaging_angle || ""),
        successCriteria: String(rawPlan.success_criteria || ""),
      };

      let recommendations: DiscoveryRecommendation[] = [];
      let narrativeTitle: string;
      let narrativeLines: string[];

      if (status === "searching" || status === "queued") {
        narrativeTitle = "Research in progress";
        narrativeLines = [
          "Working through discovery…",
          d.query ? `Query: ${d.query}` : "Refining results against your ICP.",
        ];
      } else if (status === "failed" || status === "cancelled") {
        narrativeTitle = "Research stopped";
        narrativeLines = [
          `The search for "${d.query || "this market"}" did not complete.`,
          "Try telling Loqi the market again to refine the query.",
        ];
      } else {
        const qualificationByCompany = new Map<string, DiscoveryRecommendation["qualification"]>();
        for (const lead of leads) {
          const workspaceLead = isRecord(lead.workspace_lead) ? lead.workspace_lead : {};
          const qualification: DiscoveryRecommendation["qualification"] | null =
            qualificationFromPersistedMetadata(workspaceLead.metadata) as DiscoveryRecommendation["qualification"] | null;
          if (qualification && workspaceLead.company_id) {
            qualificationByCompany.set(String(workspaceLead.company_id), qualification);
          }
        }
        recommendations = companies.map((c, i) =>
          _companyToRecommendation(
            c.company || {},
            i,
            qualificationByCompany.get(String(c.company_id || (c.company as Record<string, unknown> | undefined)?.id || "")),
          ),
        );
        if (recommendations.length === 0 && leads.length > 0) {
          recommendations = leads.map((l, i) =>
            workspaceLeadToRecommendation(l.workspace_lead || {}, i),
          );
        }
        const companyCount = companies.length;
        narrativeTitle = "Research complete";
        narrativeLines = [
          companyCount > 0
            ? `I surfaced ${companyCount} compan${companyCount === 1 ? "y" : "ies"} worth your attention.`
            : "No new prospects matched your ICP this time.",
          "Review the recommendations below and decide who to pursue.",
        ];
      }

      return {
        id: String(d.id),
        query: String(d.query || ""),
        status,
        createdAt: String(d.created_at || ""),
        completedAt: d.completed_at ? String(d.completed_at) : null,
        companyCount: companies.length,
        leadCount: leads.length,
        providers: providerCounts,
        narrativeTitle,
        narrativeLines,
        filters: [],
        recommendations,
        title: d.title ?? null,
        description: d.description ?? null,
        favorite: Boolean(d.favorite),
        archivedAt: d.archived_at ? String(d.archived_at) : null,
        lastViewedAt: d.last_viewed_at ? String(d.last_viewed_at) : null,
        lastRefreshedAt: d.last_refreshed_at ? String(d.last_refreshed_at) : null,
        metadata: d.metadata || {},
        progress,
        plan,
      };
    } catch {
      return null;
    }
  });
}

export function prefetchDiscovery(id: string): Promise<DiscoveryData | null> {
  return memoizedFetch(sessionKey(`discovery:${id}`), () => fetchDiscovery(id));
}

export function peekCachedDiscovery(id: string): DiscoveryData | null {
  return peekCached<DiscoveryData>(`discovery:${id}`);
}

/**
 * Bypass the memoized cache and hit the API now. Used by the detail page's
 * polling loop while a run is in flight — the memoized fetch would otherwise
 * throttle real updates to the 20s cache TTL and the UI would look stuck.
 */
export async function fetchDiscoveryFresh(id: string): Promise<DiscoveryData | null> {
  fetchCache.delete(sessionKey(`discovery:${id}`));
  return fetchDiscovery(id);
}

export function invalidateDiscoveryCache(): void {
  fetchCache.delete(sessionKey("discovery-list"));
}

export async function startDiscoverySearch(query: string): Promise<{ jobId: string; discoveryId: string } | null> {
  const token = getToken();
  console.log("[kickoff] startDiscoverySearch: enter", { tokenPresent: !!token, query: query.slice(0, 80) });
  if (!token || !query.trim()) {
    console.log("[kickoff] startDiscoverySearch: ABORT (no token or empty query)");
    return null;
  }
  const res = await startDiscoveryJob(token, query.trim());
  console.log("[kickoff] startDiscoverySearch: startDiscoveryJob resolved", res);
  if (res && res.discovery_id) {
    invalidateDiscoveryCache();
    console.log("[kickoff] startDiscoverySearch: OK ->", { jobId: res.job_id, discoveryId: res.discovery_id });
    return { jobId: String(res.job_id), discoveryId: String(res.discovery_id) };
  }
  console.log("[kickoff] startDiscoverySearch: null (no discovery_id in response)");
  return null;
}
