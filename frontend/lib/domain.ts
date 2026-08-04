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
};

export type DiscoveryFilter = {
  id: string;
  label: string;
};

export type DiscoveryData = {
  narrativeTitle: string;
  narrativeLines: string[];
  filters: DiscoveryFilter[];
  recommendations: DiscoveryRecommendation[];
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

export type CampaignData = {
  id?: string;
  name: string;
  status: string;
  createdAt: string;
  objective: string;
  leadCount?: number;
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

export type InboxDecisionAction = {
  label: string;
};

export type InboxDecisionDetail = {
  aiSummary: string;
  timeline: { time: string; label: string; event: string }[];
  concerns: { type: "warning" | "info"; text: string }[];
  recommendedReply: string;
  originalConversation: { name: string; role: string; text: string }[];
};

export type InboxDecision = {
  id: string;
  title: string;
  company: string;
  icon: string;
  badge: string;
  summary: string;
  recommendedDecision: string;
  actions: {
    primary: InboxDecisionAction;
    secondary: InboxDecisionAction;
  };
  footerLink: { label: string };
  detail: InboxDecisionDetail;
};

export type InboxAutoAction = {
  text: string;
  time: string;
};

export type InboxInsight = {
  icon: string;
  title: string;
  description: string;
};

export type InboxData = {
  decisions: InboxDecision[];
  autoActions: InboxAutoAction[];
  insights: InboxInsight[];
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
