/* ─── Mission Control ─── */

export type MCTask = {
  id: string;
  title: string;
  completed: boolean;
};

export type MCBrief = {
  greeting: string;
  lines: string[];
  suggestion: string;
};

export type MCRecommendation = {
  type: string;
  observation: string;
  reason: string;
  action: string;
  confidence: string;
  link: string;
  why_details?: string[];
};

export type MCLiveActivity = {
  type: string;
  text: string;
  timestamp: string;
  count?: number;
  grouped?: boolean;
};

export type MCInsight = {
  icon: string;
  text: string;
};

export type MCData = {
  brief: MCBrief;
  tasks: MCTask[];
  recommendations: MCRecommendation[];
  liveActivity: MCLiveActivity[];
  insights: MCInsight[];
  activeJobLabel: string | null;
  activeJobProgress: number | null;
  activeJobTotal: number | null;
  initialResearchStatus: string | null;
  initialResearchError: string | null;
  initialResearchResultCount: number | null;
};

/* ─── Phase 11: Briefing-specific domain types ─── */

export type MCIntentionCard = {
  id: string;
  title: string;
  summary: string;
  priority: "critical" | "high" | "normal" | "low";
  confidence: number;
  evidence: Array<{
    reason_code: string;
    confidence: number;
    source: string;
    detail: string;
  }>;
  recommendedAction: string;
  relatedCampaign: string | null;
  relatedLead: string | null;
  reasonCode: string;
};

export type MCBriefing = {
  greeting: string;
  lines: string[];
  suggestion: string;
  overallSummary: string;
  primaryFocus: string;
  topRecommendation: string;
};

export type MCHealthSummary = {
  overallHealth: string;
  pipelineVelocity: string;
  bottlenecks: string[];
  providerHealth: Array<Record<string, unknown>>;
  confidenceScore: number;
  campaignsReady: number;
  campaignsWaiting: number;
  draftBacklog: number;
  details: Record<string, unknown>;
};

export type MCTimelineEvent = {
  id: string;
  timestamp: string;
  type: string;
  description: string;
  category: string;
  actor: string;
};

export type MCBriefingData = {
  briefing: MCBriefing;
  topPriorities: MCIntentionCard[];
  waitingOnYou: MCIntentionCard[];
  loqiHandled: MCIntentionCard[];
  upcoming: MCIntentionCard[];
  workspaceHealth: MCHealthSummary;
  timeline: MCTimelineEvent[];
};

/* ─── Discovery ─── */

export type DiscoveryAlsoConsidered = {
  name: string;
  note: string;
  error?: boolean;
};

export type DiscoveryRecommendation = {
  id: string;
  company: string;
  match: number;
  subtitle: string;
  stage: string;
  location: string;
  reasoning: string;
  buyingSignal: string;
  signalDetail: string;
  funding: string;
  hiring: string;
  alsoConsidered: DiscoveryAlsoConsidered[];
  qualification?: DiscoveryQualification;
};

export type DiscoveryQualification = {
  prospect_evidence?: Array<{ field: string; value: string }>;
  structured_icp_match?: {
    matched_roles?: string[];
    matched_industries?: string[];
    influenced_dimensions?: string[];
  };
  knowledge_context?: {
    knowledge_item_ids?: string[];
    knowledge_source_ids?: string[];
    retrieval_query?: string;
    contributed_fields?: string[];
    guidance_only?: boolean;
  };
  strategic_observations?: {
    strategic_update_ids?: string[];
    observations?: Array<{ id: string; title: string; observation: string; observation_only?: boolean }>;
    guidance_only?: boolean;
  };
};

export type DiscoveryFilter = {
  id: string;
  label: string;
};

export type DiscoveryStatus = "queued" | "searching" | "completed" | "failed" | "cancelled";

/**
 * Live execution tick persisted on the discovery (metadata.progress) by the
 * job runner: the current stage label + a 0-100 percent.
 */
export type DiscoveryProgress = {
  stage?: string;
  progress?: number;
};

/**
 * The structured Discovery Plan derived from the raw objective before any
 * search is run. The provider only ever consumes these structured terms —
 * never the raw objective sentence.
 */
export type DiscoveryPlan = {
  offering: string;
  primaryServices: string[];
  targetAudience: string;
  industries: string[];
  subIndustries: string[];
  icpSummary: string;
  buyerPersonas: string[];
  companyKeywords: string[];
  decisionMakerRoles: string[];
  negativeKeywords: string[];
  painPoints: string[];
  buyingSignals: string[];
  technologies: string[];
  businessCharacteristics: string[];
  exclusions: string[];
  geography: string[];
  companySize: string[];
  messagingAngle: string;
  successCriteria: string;
};

export type DiscoveryListItem = {
  id: string;
  query: string;
  status: DiscoveryStatus;
  companyCount: number;
  leadCount: number;
  createdAt: string;
  completedAt: string | null;
  summary: Record<string, unknown>;
  title?: string | null;
  description?: string | null;
  favorite?: boolean;
  archivedAt?: string | null;
  lastViewedAt?: string | null;
  lastRefreshedAt?: string | null;
  metadata?: Record<string, unknown>;
};

export type DiscoveryData = {
  id: string;
  query: string;
  status: DiscoveryStatus;
  createdAt: string;
  completedAt: string | null;
  companyCount: number;
  leadCount: number;
  providers: Record<string, number>;
  narrativeTitle: string;
  narrativeLines: string[];
  filters: DiscoveryFilter[];
  recommendations: DiscoveryRecommendation[];
  title?: string | null;
  description?: string | null;
  favorite?: boolean;
  archivedAt?: string | null;
  lastViewedAt?: string | null;
  lastRefreshedAt?: string | null;
  metadata?: Record<string, unknown>;
  progress?: DiscoveryProgress;
  plan?: DiscoveryPlan;
};

/* ─── Campaigns ─── */

export type CampaignMilestone = {
  label: string;
  description: string;
  status: "completed" | "in_progress" | "pending";
};

export type CampaignImprovement = {
  description: string;
  reasoning: string;
};

export type CampaignTimelineEntry = {
  date: string;
  events: string[];
};

export type CampaignInsight = {
  icon: string;
  text: string;
  footnote: string;
};

export type CampaignLaunchProgress = {
  status: string;
  total: number;
  sent: number;
  failed: number;
};

export type CampaignData = {
  id?: string;
  name: string;
  status: string;
  currentStep?: string;
  generation?: {
    status?: string;
    total?: number;
    completed?: number;
    batch_id?: string;
  };
  createdAt: string;
  objective: string;
  discoveryId?: string;
  leadCount?: number;
  pendingDrafts?: number;
  approvedDrafts?: number;
  launch?: CampaignLaunchProgress;
  leads?: Array<Record<string, unknown>>;
  strategy?: Record<string, unknown> | null;
  milestones: CampaignMilestone[];
  improvements: CampaignImprovement[];
  timeline: CampaignTimelineEntry[];
  insights: CampaignInsight[];
  recommendation: {
    title: string;
    body: string;
  };
};

/* ─── Inbox ─── */

export type InboxConversationRow = {
  id: string;
  name: string;
  email: string;
  company: string;
  status: string;
  /** Loqi reply classification (metadata.last_reply_category from backend). */
  classification: string;
  interest: string;
  preview: string;
  lastActivityAt: string;
  messageCount: number;
};

export type InboxData = {
  rows: InboxConversationRow[];
};

/* ─── Knowledge ─── */

export type KnowledgeField = {
  label: string;
  value: string;
  variant?: "default" | "quote" | "tags";
  tags?: string[];
};

export type KnowledgeCard = {
  id: string;
  category: string;
  title: string;
  confidence: string;
  confidenceMode: "high" | "medium" | "low" | "learning";
  fields: KnowledgeField[];
};

export type KnowledgeTimelineEntry = {
  time: string;
  event: string;
  highlight: boolean;
};

export type KnowledgeEvolutionEntry = {
  label: string;
};

export type KnowledgeData = {
  cards: KnowledgeCard[];
  timeline: KnowledgeTimelineEntry[];
  evolution: KnowledgeEvolutionEntry[];
  lastSync: string;
  brainVersion: string;
};

/* ─── Strategic Update ─── */

export type StrategicAdjustment = {
  area: string;
  icon: string;
  title: string;
  description: string;
  colSpan: boolean;
};

export type StrategicImpact = {
  label: string;
  value: string;
  severity: "high" | "medium";
};

export type StrategicData = {
  subtitle: string;
  understanding: string;
  adjustments: StrategicAdjustment[];
  impacts: StrategicImpact[];
  recommendation: string;
  phaseLabel: string;
  phaseProgress: number;
  stableContinuity: string[];
  affectedAreas: string[];
};
