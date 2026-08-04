import {
  getMissionControl,
  getBriefing,
  getCampaign,
  listCampaigns,
  listActiveJobs,
  listConversations,
  getJobResults,
  startSearchJob,
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
  CampaignData,
  InboxData,
  InboxDecision,
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

/* ─── Utilities ─── */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

export function prefetchDiscovery(): Promise<DiscoveryData | null> {
  return memoizedFetch(sessionKey("discovery"), fetchDiscovery);
}

export function peekCachedDiscovery(): DiscoveryData | null {
  return peekCached<DiscoveryData>("discovery");
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
    createdAt: (c.created_at as string) || "",
    objective: (c.objective as string) || "",
    leadCount: Number(c.lead_count || 0),
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

const JUDGMENT_STATUSES = new Set([
  "replied",
  "interested",
  "follow_up_ready",
  "bounced",
  "follow_up_pending",
]);

function inboxDecisionFromConversation(c: Record<string, unknown>): InboxDecision {
  const id = String(c.conversation_id || c.id || "");
  const status = String(c.status || "unknown");
  const participants = Array.isArray(c.participants) ? c.participants : [];
  const primary = (participants[0] as Record<string, unknown> | undefined) || {};
  const name = String(primary.name || primary.email || "Contact");
  const company = String(c.company_name || c.campaign_name || primary.company || "Unknown company");
  const summary = String(
    c.last_message_preview || c.summary || c.subject || `Conversation status: ${status}`,
  );

  const badge =
    status === "interested"
      ? "Interested"
      : status === "bounced"
        ? "Bounced"
        : status === "follow_up_ready"
          ? "Follow-up ready"
          : "Needs reply";

  const recommendedDecision =
    status === "interested"
      ? "Approve a meeting-oriented reply"
      : status === "bounced"
        ? "Investigate bounce and pause outreach"
        : "Review and decide on next reply";

  return {
    id,
    title: name,
    company,
    icon: status === "bounced" ? "error" : status === "interested" ? "handshake" : "mail",
    badge,
    summary,
    recommendedDecision,
    actions: {
      primary: { label: "Review conversation" },
      secondary: { label: "Open details" },
    },
    footerLink: { label: "Open conversation" },
    detail: {
      aiSummary: summary,
      timeline: [],
      concerns: [],
      recommendedReply: "",
      originalConversation: [],
    },
  };
}

export async function fetchInbox(): Promise<InboxData | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const raw = await listConversations(token);
    const conversations = Array.isArray(raw.conversations) ? raw.conversations : [];
    const decisions = conversations
      .filter((c) => JUDGMENT_STATUSES.has(String((c as Record<string, unknown>).status || "")))
      .map((c) => inboxDecisionFromConversation(c as Record<string, unknown>));

    return {
      decisions,
      autoActions: [],
      insights: decisions.length
        ? [
            {
              icon: "priority_high",
              title: "Human judgment required",
              description: `${decisions.length} conversation${decisions.length === 1 ? "" : "s"} need your decision.`,
            },
          ]
        : [],
    };
  } catch {
    return { decisions: [], autoActions: [], insights: [] };
  }
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

const DISCOVERY_JOB_KEY = "loqi_discovery_last_job_id";

export function getStoredDiscoveryJobId(): string | null {
  try {
    return sessionStorage.getItem(DISCOVERY_JOB_KEY);
  } catch {
    return null;
  }
}

export function storeDiscoveryJobId(jobId: string): void {
  try {
    sessionStorage.setItem(DISCOVERY_JOB_KEY, jobId);
  } catch {
    /* ignore */
  }
}

function leadToDiscoveryRecommendation(
  lead: Record<string, unknown>,
  index: number,
): DiscoveryRecommendation {
  const company = String(lead.company || lead.company_name || "Unknown company");
  const title = String(lead.title || lead.job_title || "");
  const name = String(lead.name || lead.full_name || "");
  const location = String(lead.location || lead.city || "Unknown");
  const scoreRaw = lead.relevance_score ?? lead.score ?? lead.match_score;
  const match =
    typeof scoreRaw === "number"
      ? Math.round(scoreRaw > 1 ? scoreRaw : scoreRaw * 100)
      : Math.max(55, 90 - index * 3);

  const reasoningParts = [
    name && title ? `${name} (${title})` : name || title,
    lead.linkedin_url ? "LinkedIn profile available" : null,
    lead.email ? "Email on file" : null,
  ].filter(Boolean);

  return {
    id: String(lead.id || lead.linkedin_url || `lead-${index}`),
    company,
    match,
    subtitle: title || name || "Prospect",
    stage: String(lead.seniority || lead.stage || "Prospect"),
    location,
    reasoning: reasoningParts.join(". ") || "Matched from research job results.",
    buyingSignal: String(lead.buying_signal || lead.signal || "Research match"),
    signalDetail: String(lead.buying_signal_detail || lead.snippet || lead.headline || ""),
    funding: String(lead.funding || "—"),
    hiring: String(lead.hiring || "—"),
    alsoConsidered: [],
  };
}

export async function fetchDiscovery(): Promise<DiscoveryData | null> {
  return memoizedFetch(sessionKey("discovery"), async () => {
    const token = getToken();
    if (!token) return null;

    try {
      const recent = await listActiveJobs(token, getUserId() ?? "");
      const jobs = Array.isArray(recent.jobs) ? recent.jobs : [];
      const searchJob = jobs.find((j) =>
        j.type === "search" && (j.status === "queued" || j.status === "running"),
      );

      if (searchJob) {
        storeDiscoveryJobId(searchJob.id);
        return {
          narrativeTitle: "Research in progress",
          narrativeLines: [
            searchJob.stage || "Working through discovery…",
            searchJob.query ? `Query: ${searchJob.query}` : "Refining results against your ICP.",
            `Progress: ${searchJob.progress}%`,
          ],
          filters: [],
          recommendations: [],
        };
      }

      const completedSearch = jobs.find((j) =>
        j.type === "search" && j.status === "completed" && j.result_ready,
      );
      const storedId = getStoredDiscoveryJobId() || completedSearch?.id;
      if (storedId) {
        try {
          const results = await getJobResults(storedId);
          const leads = Array.isArray(results.leads) ? results.leads : [];
          if (leads.length > 0) {
            return {
              narrativeTitle: "Research complete",
              narrativeLines: [
                `I found ${leads.length} prospect${leads.length === 1 ? "" : "s"} worth your attention.`,
                "Review the recommendations below and decide who to pursue.",
              ],
              filters: [],
              recommendations: leads.map((l, i) =>
                leadToDiscoveryRecommendation(l as Record<string, unknown>, i),
              ),
            };
          }
        } catch {
          /* job may still be incomplete or expired */
        }
      }

      return null;
    } catch {
      return null;
    }
  });
}

export async function startDiscoverySearch(query: string): Promise<string | null> {
  const token = getToken();
  if (!token || !query.trim()) return null;
  const res = await startSearchJob(token, query.trim());
  if (res.job_id) {
    storeDiscoveryJobId(res.job_id);
    return res.job_id;
  }
  return null;
}
