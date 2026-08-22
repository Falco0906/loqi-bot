import type { LeadIntelligence, LoqiMessage, LoqiSessionSummary } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

function authHeaders(): Record<string, string> {
  try {
    const token = localStorage.getItem("loqi_access_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

export class TimeoutError extends Error {
  constructor() {
    super("Request timed out");
    this.name = "TimeoutError";
  }
}

type FetchOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  cache?: RequestCache;
  timeout?: number;
  retries?: number;
  signal?: AbortSignal;
};

/**
 * PR-P1.3: retries are method-aware. Idempotent GET/HEAD may retry
 * transient network/timeout failures; mutations (POST/PUT/PATCH/DELETE)
 * must NOT be replayed automatically because a timeout does not tell us
 * whether the backend already executed the operation. Callers can still
 * override explicitly via `retries`.
 */
const IDEMPOTENT_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function defaultRetriesFor(method: string): number {
  return IDEMPOTENT_METHODS.has(method.toUpperCase()) ? 2 : 0;
}

/**
 * Compose the caller's AbortSignal (if any) with an internal timeout signal
 * so that BOTH can abort the fetch: the caller keeps full cancel power and
 * the per-attempt timeout still fires when only a caller signal was given.
 * Returns a cleanup fn that detaches listeners after the attempt settles.
 */
function composeSignals(external: AbortSignal | undefined, controller: AbortController): () => void {
  if (!external) {
    // No caller signal: the internal timeout alone governs abortion.
    return () => {};
  }
  const onExternalAbort = () => controller.abort(external.reason);
  if (external.aborted) {
    onExternalAbort();
    return () => {};
  }
  external.addEventListener("abort", onExternalAbort);
  return () => external.removeEventListener("abort", onExternalAbort);
}

async function fetchWithRetry<T>(
  url: string,
  options: FetchOptions = {},
): Promise<T> {
  const timeout = options.timeout ?? 10000;
  const method = options.method || "GET";
  const retries = options.retries ?? defaultRetriesFor(method);
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    // PR-P1.3: never sleep or re-attempt once the caller has cancelled.
    if (options.signal?.aborted) {
      throw lastError || new DOMException("Aborted", "AbortError");
    }

    if (attempt > 0) {
      const delay = attempt === 1 ? 500 : 1000;
      await new Promise((r) => setTimeout(r, delay));
      if (options.signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    const removeSignalListeners = composeSignals(options.signal, controller);

    // PR10.8.3.1: session credentials are sent ONLY via the Authorization
    // header — never interpolated into URLs. For /api/web/session/* calls,
    // attach the active web-session token as Bearer unless a caller already
    // supplied an Authorization header (e.g. identity Bearer).
    let headers = options.headers;
    if (url.includes("/api/web/session/")) {
      const hasAuth = Object.entries((options.headers as Record<string, string>) || {})
        .some(([k]) => k.toLowerCase() === "authorization");
      if (!hasAuth) {
        try {
          const token = localStorage.getItem("loqi_active_session_token");
          if (token) {
            headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
          }
        } catch {
          /* no token available */
        }
      }
    }

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: options.body,
        cache: options.cache,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const text = await response.text();
        let message = text || `Request failed with ${response.status}`;
        try {
          const parsed: unknown = JSON.parse(text);
          if (parsed && typeof parsed === "object" && "detail" in parsed) {
            message = String((parsed as { detail: unknown }).detail || message);
          }
        } catch {
          /* keep raw text */
        }
        throw new ApiError(message, response.status);
      }

      return (await response.json()) as T;
    } catch (err) {
      clearTimeout(timeoutId);
      lastError = err as Error;

      // A caller-initiated abort ends the loop immediately — do not retry.
      if (options.signal?.aborted) {
        throw err instanceof Error ? err : new DOMException("Aborted", "AbortError");
      }

      if (err instanceof ApiError) throw err;

      if (err instanceof DOMException && err.name === "AbortError") {
        // Our own timeout fired (caller signal was ruled out above).
        lastError = new TimeoutError();
      } else if (!(err instanceof TimeoutError)) {
        lastError = new NetworkError(
          err instanceof Error ? err.message : "Failed to fetch",
        );
      }
    } finally {
      removeSignalListeners();
    }
  }

  throw lastError || new NetworkError("Failed to fetch");
}

export async function checkHealth() {
  try {
    const res = await fetchWithRetry<{
      status: string;
      version: string;
      uptime: number;
      database: string;
      providers: string;
    }>(`${API_BASE}/health`, { timeout: 5000, retries: 0 });
    return { ok: true, ...res };
  } catch {
    return { ok: false };
  }
}

export async function createSession(displayName?: string) {
  const accessToken = typeof window !== "undefined" ? localStorage.getItem("loqi_access_token") : null;
  return fetchWithRetry<{
    ok: boolean;
    session_token: string;
    gmail_connected: boolean;
  }>(`${API_BASE}/api/web/session`, {
    method: "POST",
    timeout: 35000,
    retries: 0,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function getSession(sessionToken: string) {
  return fetchWithRetry<LoqiSessionSummary>(
    `${API_BASE}/api/web/session/_`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function sendMessage(sessionToken: string, text: string) {
  return fetchWithRetry<{ ok: boolean; messages: LoqiMessage[] }>(
    `${API_BASE}/api/web/session/_/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text }),
    },
  );
}

export async function copilotMessage(
  sessionToken: string,
  params: {
    text: string;
    currentPage?: string;
    pageContext?: Record<string, unknown>;
    availableActions?: string[];
    messageHistory?: Array<{ role: string; text: string }>;
  },
) {
  return fetchWithRetry<{
    ok: boolean;
    messages: LoqiMessage[];
    events: unknown[];
    session_token?: string;
  }>(
    `${API_BASE}/api/web/session/_/messages`,
    {
      method: "POST",
      timeout: 20000,
      // PR-P1.3: a chat POST that times out may already have been processed
      // server-side — replaying it would duplicate the user's message.
      retries: 0,
      headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: params.text,
          copilot: {
            current_page: params.currentPage,
            page_context: params.pageContext,
            available_actions: params.availableActions,
            message_history: params.messageHistory,
          },
        }),
    },
  );
}

export async function selectLead(sessionToken: string, index: number) {
  return fetchWithRetry<{ ok: boolean; messages: LoqiMessage[] }>(
    `${API_BASE}/api/web/session/_/select-lead`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    },
  );
}

export async function previewLead(sessionToken: string, index: number) {
  return fetchWithRetry<{ ok: boolean; lead_intelligence: LeadIntelligence }>(
    `${API_BASE}/api/web/session/_/preview-lead`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    },
  );
}

export async function getGmailStatus(sessionToken: string) {
  const accessToken = typeof window !== "undefined" ? localStorage.getItem("loqi_access_token") : null;
  return fetchWithRetry<{
    ok: boolean;
    gmail_connected: boolean;
    connect_url: string;
  }>(`${API_BASE}/api/web/session/_/gmail`, {
    cache: "no-store",
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
}

/* ─── Campaign Planner ─── */

export async function analyzeCampaigns(sessionToken: string, leads: unknown[]) {
  return fetchWithRetry<{
    ok: boolean;
    plan_id: string;
    campaigns: Array<{
      id: string;
      name: string;
      lead_count: number;
      leads: unknown[];
      primary_signal: string;
      reason: string;
      messaging_angle: string;
      priority: number;
      message_theme: string;
    }>;
    overall_recommendation: string;
    total_leads: number;
  }>(`${API_BASE}/api/web/session/_/analyze-campaigns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ leads }),
  });
}

/* ─── Batch discovery ─── */

export async function batchDraft(sessionToken: string, leads: unknown[], campaignId?: string) {
  return fetchWithRetry<{ ok: boolean; batch_id: string; total: number }>(
    `${API_BASE}/api/web/session/_/batch-draft`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leads, campaign_id: campaignId }),
    },
  );
}

export async function batchStatus(sessionToken: string, batchId: string) {
  return fetchWithRetry<{
    ok: boolean;
    status: string;
    total: number;
    completed: number;
    current_index: number;
    current_name: string | null;
    drafts: Array<{
      id: string;
      lead: unknown;
      text: string;
      status: string;
      tone?: string;
      length?: string;
      company_intelligence?: unknown;
      lead_intelligence?: unknown;
    }>;
  }>(`${API_BASE}/api/web/session/_/batch-status/${batchId}`);
}

/* ─── Draft CRUD ─── */

export async function listDrafts(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; drafts: unknown[] }>(
    `${API_BASE}/api/web/session/_/drafts`,
    { headers: authHeaders() },
  );
}

export async function updateDraft(sessionToken: string, draftId: string, text: string) {
  return fetchWithRetry<{ ok: boolean; draft: unknown }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text }),
    },
  );
}

export async function refineDraft(
  sessionToken: string,
  draftId: string,
  editRequest: string,
  previousMessage: string,
  lead: unknown,
  context?: {
    campaign_id?: string;
    campaign_name?: string;
    company?: string;
    contact?: string;
    role?: string;
    industry?: string;
    messaging_angle?: string;
    business_summary?: string;
  },
) {
  const body: Record<string, unknown> = { edit_request: editRequest, previous_message: previousMessage, lead };
  if (context) {
    for (const [k, v] of Object.entries(context)) {
      if (v !== undefined && v !== null) body[k] = v;
    }
  }
  return fetchWithRetry<{ ok: boolean; draft: { id: string; text: string; status: string }; rewritten_text?: string; change_summary?: string[]; draft_intelligence?: DraftIntelligence | null; version?: number; confidence?: string; comparison?: { improvements: Array<{ category: string; description: string }>; regressions: Array<{ category: string; description: string }>; added: string[]; removed: string[]; length_change_pct: number } }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/refine`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    },
  );
}

export type DraftIntelligenceCategory = {
  score: number;
  label?: string;
  reason: string;
  improvement: string;
};

export type DraftIntelligence = {
  opening_strength: DraftIntelligenceCategory;
  personalization_quality: DraftIntelligenceCategory;
  pain_alignment: DraftIntelligenceCategory;
  relevance: DraftIntelligenceCategory;
  credibility: DraftIntelligenceCategory;
  cta_strength: DraftIntelligenceCategory;
  readability: DraftIntelligenceCategory;
  length: DraftIntelligenceCategory;
  tone: DraftIntelligenceCategory;
  confidence: DraftIntelligenceCategory;
  patterns: string[];
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  persona_analysis?: Record<string, unknown> | null;
  persona?: Record<string, unknown> | null;
  company_context?: Record<string, unknown> | null;
  messaging_strategy?: Record<string, unknown> | null;
  cta_recommendation?: Record<string, unknown> | null;
  objection_predictions?: Record<string, unknown>[] | null;
  trust_suggestions?: Record<string, unknown>[] | null;
  framework_recommendation?: Record<string, unknown> | null;
};

export type DraftAnalysis = {
  quality_score: number;
  strengths: string[];
  weaknesses: string[];
  biggest_opportunity: string;
  estimated_reply_rate: string;
  recommended_actions: string[];
};

export async function analyzeDraft(
  sessionToken: string,
  draftText: string,
  lead: unknown,
  context?: {
    campaign_id?: string;
    campaign_name?: string;
    company?: string;
    contact?: string;
    role?: string;
    industry?: string;
    messaging_angle?: string;
    business_summary?: string;
  },
) {
  const body: Record<string, unknown> = { draft_text: draftText, lead };
  if (context) {
    for (const [k, v] of Object.entries(context)) {
      if (v !== undefined && v !== null) body[k] = v;
    }
  }
  return fetchWithRetry<{ ok: boolean; analysis: DraftAnalysis | null; draft_intelligence?: DraftIntelligence | null; error?: string }>(
    `${API_BASE}/api/web/session/_/drafts/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function undoDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; draft: { id: string; text: string; status: string }; undo?: { previous_text: string; reason: string; strategy: string; change_summary: string[]; version: number; timestamp: string } }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/undo`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function getDraftHistory(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; history: Array<{ previous_text: string; reason: string; strategy: string; change_summary: string[]; version: number; timestamp: string }>; current_version?: number }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/history`,
    { cache: "no-store" },
  );
}

export async function compareDraftVersions(
  sessionToken: string,
  oldText: string,
  newText: string,
  changeSummary?: string[],
) {
  return fetchWithRetry<{ ok: boolean; comparison: { improvements: Array<{ category: string; description: string }>; regressions: Array<{ category: string; description: string }>; added: string[]; removed: string[]; length_change_pct: number } }>(
    `${API_BASE}/api/web/session/_/drafts/compare`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_text: oldText, new_text: newText, change_summary: changeSummary }),
    },
  );
}

export async function askDraftQuestion(
  sessionToken: string,
  question: string,
  draftText: string,
  lead: unknown,
  context?: {
    campaign_id?: string;
    campaign_name?: string;
    company?: string;
    contact?: string;
    role?: string;
    industry?: string;
    messaging_angle?: string;
    business_summary?: string;
  },
) {
  const body: Record<string, unknown> = { question, draft_text: draftText, lead };
  if (context) {
    for (const [k, v] of Object.entries(context)) {
      if (v !== undefined && v !== null) body[k] = v;
    }
  }
  return fetchWithRetry<{ ok: boolean; answer?: string; error?: string }>(
    `${API_BASE}/api/web/session/_/drafts/ask`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function approveDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{
    ok: boolean;
    draft: {
      id: string;
      campaign_id?: string;
      lead?: Record<string, unknown>;
      subject?: string;
      text: string;
      status: string;
      tone?: string;
      length?: string;
      lead_intelligence?: Record<string, unknown>;
      company_intelligence?: Record<string, unknown>;
      created_at?: string;
    };
    campaign_status?: string | null;
    current_step?: string | null;
    pending_drafts?: number;
  }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/approve`,
    { method: "POST", headers: authHeaders() },
  );
}

export async function sendDraft(
  sessionToken: string,
  draftId: string,
  options: { test_recipient?: string; test_recipient_name?: string } = {},
) {
  const body = options.test_recipient
    ? JSON.stringify({
        test_recipient: options.test_recipient,
        test_recipient_name: options.test_recipient_name || "Test Recipient",
      })
    : undefined;
  return fetchWithRetry<{ ok: boolean; error?: string; send_result?: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/send`,
    {
      method: "POST",
      ...(body ? { headers: { "Content-Type": "application/json" }, body } : {}),
    },
  );
}

export async function scheduleDraft(sessionToken: string, draftId: string, sendAt: string) {
  return fetchWithRetry<{ ok: boolean; schedule_id?: string; error?: string }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/schedule`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ send_at: sendAt }) },
  );
}

export async function cancelScheduleDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; error?: string }>(
    `${API_BASE}/api/web/session/_/drafts/${draftId}/cancel-schedule`,
    { method: "POST" },
  );
}

/* ─── Campaigns ─── */

export async function saveCampaign(
  sessionToken: string,
  name: string,
  objective?: string,
  searchQuery?: string,
  leadCount?: number,
  strategy?: unknown,
  status?: string,
  leads?: unknown[],
  discoveryId?: string,
) {
  return fetchWithRetry<{ ok: boolean; campaign: unknown }>(
    `${API_BASE}/api/web/session/_/campaigns`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        name,
        objective,
        search_query: searchQuery,
        lead_count: leadCount,
        strategy,
        status: status || "planning",
        leads,
        discovery_id: discoveryId,
      }),
    },
  );
}

export async function generateCampaignStrategy(
  sessionToken: string,
  campaignId: string,
  force = false,
) {
  return fetchWithRetry<
    {
      ok: boolean;
      job_id: string | null;
      status: string;
      reused?: boolean;
      strategy?: Record<string, unknown> | null;
    }
  >(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/generate-strategy`,
    {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ force }),
      timeout: 15000,
      // PR-P1.3: strategy start creates a backend job; a replayed POST would
      // enqueue a second generation for the same campaign.
      retries: 0,
    },
  );
}

export async function getStrategyGenerationStatus(
  sessionToken: string,
  campaignId: string,
  jobId: string,
) {
  return fetchWithRetry<{
    job_id: string;
    status: "queued" | "running" | "completed" | "failed";
    strategy?: Record<string, unknown> | null;
    error?: string | null;
  }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/strategy-jobs/${jobId}`,
    { timeout: 8000, retries: 1 },
  );
}

export async function addLeadToCampaign(
  sessionToken: string,
  campaignId: string,
  lead: Record<string, unknown>,
  discoveryId?: string,
) {
  return fetchWithRetry<{ ok: boolean; added: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/leads`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ lead, discovery_id: discoveryId || undefined }),
    },
  );
}

export async function decideLead(
  sessionToken: string,
  lead: Record<string, unknown>,
  approved: boolean,
) {
  return fetchWithRetry<{ ok: boolean; lead: Record<string, unknown>; approved: boolean }>(
    `${API_BASE}/api/web/session/_/leads/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ lead, approved }),
    },
  );
}

export async function listCampaigns(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; campaigns: Array<Record<string, unknown>> }>(
    `${API_BASE}/api/web/session/_/campaigns`,
    { headers: authHeaders() },
  );
}

export async function getCampaign(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}`,
    { headers: authHeaders() },
  );
}

export async function updateCampaign(
  sessionToken: string,
  campaignId: string,
  updates: { name?: string; objective?: string; strategy?: unknown; status?: string },
) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(updates),
    },
  );
}

export async function archiveCampaign(sessionToken: string, campaignId: string) {
  return updateCampaign(sessionToken, campaignId, { status: "archived" });
}

export async function deleteCampaign(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}`,
    { method: "DELETE", headers: authHeaders() },
  );
}

export async function duplicateCampaign(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/duplicate`,
    { method: "POST", headers: authHeaders() },
  );
}

export async function attachDiscoveryToCampaign(
  sessionToken: string,
  campaignId: string,
  discoveryId: string,
) {
  return fetchWithRetry<{ ok: boolean; added: number; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/attach-discovery`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ discovery_id: discoveryId }),
    },
  );
}

export async function listCampaignDrafts(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; drafts: unknown[] }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/drafts`,
    { headers: authHeaders() },
  );
}

export async function getCampaignSummary(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; campaigns: Array<{
    id: string;
    name: string;
    status: string;
    lead_count: number;
    pending_drafts: number;
    updated_at: string;
  }> }>(
    `${API_BASE}/api/web/session/_/campaigns/summary`,
    { headers: authHeaders() },
  );
}

export type NeedAttentionItem = {
  type: string;
  campaign_id: string | null;
  campaign_name: string | null;
  label: string;
  priority: string;
  action: string;
};

export type RecentOutcome = {
  type: string;
  text: string;
  timestamp: string;
  count?: number;
  grouped?: boolean;
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

export type MCCampaign = {
  id: string;
  name: string;
  status: string;
  lead_count: number;
  pending_drafts: number;
  approved_drafts: number;
  updated_at: string;
};

export type MCBrief = {
  greeting: string;
  lines: string[];
  suggestion: string;
};

export type MCSummary = {
  ok: boolean;
  campaigns: MCCampaign[];
  draft_counts: { pending: number; approved: number; total: number };
  needs_attention: NeedAttentionItem[];
  live_activity: RecentOutcome[];
  campaign_count: number;
  active_jobs: unknown[];
  initial_research?: Record<string, unknown> | null;
  initial_research_result_count?: number | null;
  recommendations: MCRecommendation[];
  kpis: {
    estimated_reply_rate: number;
    pending_reviews: number;
    campaigns_ready: number;
  };
  total_leads: number;
  brief: MCBrief;
  workspace_memory: Record<string, unknown>;
  workspace_analysis: {
    current_focus: Record<string, unknown>;
    recommended_next_action: Record<string, unknown>;
    campaign_priorities: Array<Record<string, unknown>>;
    workspace_health: Record<string, unknown>;
    cross_campaign_insights: Array<Record<string, unknown>>;
    workflow_continuation: Record<string, unknown>;
  };
};

export async function getMissionControl(sessionToken: string, onboardingUserId = "") {
  return fetchWithRetry<MCSummary>(
    `${API_BASE}/api/web/session/_/mission-control?onboarding_user_id=${encodeURIComponent(onboardingUserId)}`,
    { headers: authHeaders() },
  );
}

/* ─── Campaign Draft Generation ─── */

export async function generateCampaignDrafts(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; batch_id: string; total: number }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/generate-drafts`,
    { method: "POST", headers: authHeaders(), timeout: DRAFT_BATCH_START_TIMEOUT_MS, retries: 0 },
  );
}

export async function getCampaignGenerationStatus(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{
    ok: boolean;
    active: boolean;
    status?: string;
    total?: number;
    completed?: number;
    batch_id?: string;
  }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/generation-status`,
    { headers: authHeaders(), timeout: 20000, retries: 1 },
  );
}

/* ─── Export ─── */

export function getExportCsvUrl(sessionToken: string) {
  return `${API_BASE}/api/web/session/_/export-csv`;
}

/* ─── Job Engine ─── */

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type JobResponse = {
  id: string;
  user_id: string;
  type: string;
  status: JobStatus;
  stage: string;
  progress: number;
  query: string;
  error_message: string | null;
  result_ready: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

/**
 * Budget for creating a Discovery search job. Job creation resolves the web
 * session and inserts a row before returning a job_id, so it can exceed the
 * standard 5s API timeout under load. It intentionally covers ONLY
 * /api/jobs/search — subsequent progress/results polling keeps the standard
 * short timeouts.
 */
export const DISCOVERY_SEARCH_START_TIMEOUT_MS = 20000;

/**
 * Budget for POSTing a draft-batch request. The endpoint starts the batch and
 * returns quickly, but starting it can exceed the standard timeout under load.
 * Retries must stay at 0: the backend treats a completed generation as
 * idempotent, and a retried POST would otherwise race batch completion.
 */
export const DRAFT_BATCH_START_TIMEOUT_MS = 30000;

export async function startSearchJob(sessionToken: string, query: string) {
  return fetchWithRetry<{ job_id: string; status: string; discovery_id: string }>(
    `${API_BASE}/api/jobs/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${sessionToken}` },
      body: JSON.stringify({ query }),
      timeout: DISCOVERY_SEARCH_START_TIMEOUT_MS,
      retries: 0,
    },
  );
}

export async function startDiscoveryJob(sessionToken: string, query: string) {
  console.log("[kickoff] startDiscoveryJob: firing POST /api/discoveries", {
    tokenPrefix: sessionToken?.slice(0, 8),
    query,
    url: `${API_BASE}/api/discoveries`,
  });
  try {
    const res = await fetchWithRetry<{ ok: boolean; job_id: string; discovery_id: string; status: string }>(
      `${API_BASE}/api/discoveries`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${sessionToken}` },
        body: JSON.stringify({ query }),
        timeout: DISCOVERY_SEARCH_START_TIMEOUT_MS,
        retries: 0,
      },
    );
    console.log("[kickoff] startDiscoveryJob: response", res);
    return res;
  } catch (err) {
    console.error("[kickoff] startDiscoveryJob: REJECTED/THREW", err);
    throw err;
  }
}

export type DiscoveryListItemResponse = {
  id: string;
  query: string;
  status: string;
  company_count: number;
  lead_count: number;
  created_at: string;
  completed_at: string | null;
  summary: Record<string, unknown>;
  title?: string | null;
  description?: string | null;
  favorite?: boolean;
  archived_at?: string | null;
  last_viewed_at?: string | null;
  last_refreshed_at?: string | null;
  metadata?: Record<string, unknown>;
};

export async function listDiscoveries(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; discoveries: DiscoveryListItemResponse[] }>(
    `${API_BASE}/api/discoveries`,
    { headers: { Authorization: `Bearer ${sessionToken}` }, timeout: 8000, retries: 0 },
  );
}

export type DiscoveryDetailResponse = {
  id: string;
  query: string;
  status: string;
  summary: Record<string, unknown>;
  filters: unknown[];
  provider_provenance: Record<string, number>;
  created_at: string;
  completed_at: string | null;
  title?: string | null;
  description?: string | null;
  favorite?: boolean;
  archived_at?: string | null;
  last_viewed_at?: string | null;
  last_refreshed_at?: string | null;
  metadata?: Record<string, unknown>;
  discovery_companies: Array<{
    rank: number;
    match_score: number;
    company_id: string;
    company: Record<string, unknown>;
  }>;
  discovery_leads: Array<{
    rank: number;
    match_score: number;
    status: string;
    lead_id: string;
    workspace_lead: Record<string, unknown>;
  }>;
};

export async function getDiscovery(sessionToken: string, discoveryId: string) {
  return fetchWithRetry<{ ok: boolean; discovery: DiscoveryDetailResponse }>(
    `${API_BASE}/api/discoveries/${discoveryId}`,
    { headers: { Authorization: `Bearer ${sessionToken}` }, timeout: 8000, retries: 0 },
  );
}

// PR-4 HOTFIX: job-status/results endpoints authenticate via the ACTIVE
// WEB-SESSION token (same credential that created the discovery). These
// calls previously sent no Authorization header at all → 401 → uncontrolled
// poll loop. Explicit header (not URL params), same as startSearchJob.
export async function getJob(jobId: string, sessionToken?: string) {
  let token = sessionToken ?? null;
  if (!token) {
    try { token = localStorage.getItem("loqi_active_session_token"); } catch { /* noop */ }
  }
  return fetchWithRetry<JobResponse>(
    `${API_BASE}/api/jobs/${jobId}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 5000,
      retries: 0,
    },
  );
}

export async function getJobResults(jobId: string, sessionToken?: string) {
  let token = sessionToken ?? null;
  if (!token) {
    try { token = localStorage.getItem("loqi_active_session_token"); } catch { /* noop */ }
  }
  return fetchWithRetry<{ ok: boolean; leads: Record<string, unknown>[] }>(
    `${API_BASE}/api/jobs/${jobId}/results`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 5000,
      retries: 0,
    },
  );
}

/* ─── Provider / Communication Intelligence (Dev Tooling) ─── */

export async function getGmailAuthUrl(sessionToken?: string) {
  const params = sessionToken ? `?session_token=${encodeURIComponent(sessionToken)}` : '';
  const accessToken = typeof window !== "undefined" ? localStorage.getItem("loqi_access_token") : null;
  return fetchWithRetry<{ ok: boolean; url: string }>(
    `${API_BASE}/api/auth/gmail/url${params}`,
    { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} },
  );
}

export async function getGmailCallback(code: string) {
  return fetchWithRetry<{ ok: boolean; provider_id?: string; email?: string; error?: string }>(
    `${API_BASE}/api/auth/gmail/callback?code=${encodeURIComponent(code)}`,
  );
}

export async function listProviders(sessionToken: string) {
  // PR-2A §8 auth note (verified, not changed): the URL contains
  // "/api/web/session/", so fetchWithRetry injects the ACTIVE WEB-SESSION
  // token from localStorage ("loqi_active_session_token") as the Bearer
  // header — exactly the credential the backend's session resolver expects.
  // Deliberately NOT using authHeaders() here: that would send the identity
  // access token instead and SUPPRESS the session-token injection.
  return fetchWithRetry<{ ok: boolean; providers: Array<{
    id: string; provider_type: string; status: string;
    email: string; last_sync: string; sync_cursor: string; created_at: string;
  }> }>(
    `${API_BASE}/api/web/session/_/providers`,
    { cache: "no-store" },
  );
}

export async function connectProvider(sessionToken: string, providerType: string, authToken: string, email?: string) {
  return fetchWithRetry<{ ok: boolean; provider: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/providers/connect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider_type: providerType, auth_token: authToken, email }),
    },
  );
}

export async function disconnectProvider(sessionToken: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean }>(
    `${API_BASE}/api/web/session/_/providers/${providerId}/disconnect`,
    { method: "POST" },
  );
}

export async function getProviderHealth(sessionToken: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean; provider_id: string; status: string; last_sync: string }>(
    `${API_BASE}/api/web/session/_/providers/${providerId}/health`,
  );
}

export async function syncProvider(sessionToken: string, providerId: string, cursor?: string) {
  const params = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  return fetchWithRetry<{ ok: boolean; result: {
    provider_id: string; threads_synced: number; messages_synced: number;
    new_conversations: number; errors: string[]; cursor: string; duration_ms: number;
  } }>(
    `${API_BASE}/api/web/session/_/providers/${providerId}/sync${params}`,
    { method: "POST", timeout: 30000 },
  );
}

export async function getProviderStatus(sessionToken: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean; provider_id: string; provider_type: string; status: string;
    connected: boolean; last_sync: string; sync_cursor: string; watching: boolean;
  }>(`${API_BASE}/api/web/session/_/providers/${providerId}/status`);
}

export async function getProviderThreads(sessionToken: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean; provider_id: string; threads: Array<Record<string, unknown>>; total: number }>(
    `${API_BASE}/api/web/session/_/providers/${providerId}/threads`,
  );
}

export async function getProviderMessages(sessionToken: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean; provider_id: string; total_messages_seen: number; recent_messages?: Record<string, unknown>[]; mailbox_email?: string }>(
    `${API_BASE}/api/web/session/_/providers/${providerId}/messages`,
  );
}

export async function getProviderEvents(sessionToken: string, providerId?: string, after?: number) {
  const params = new URLSearchParams();
  if (providerId) params.set("provider_id", providerId);
  if (after !== undefined) params.set("after", String(after));
  const qs = params.toString();
  return fetchWithRetry<{ ok: boolean; events: Array<{
    id: string; event_type: string; provider_id: string;
    message: string; timestamp: string; sequence: number; metadata: Record<string, unknown>;
  }>; latest_sequence: number }>(
    `${API_BASE}/api/web/session/_/providers/events${qs ? '?' + qs : ''}`,
  );
}

export async function getRegisteredProviderTypes(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; types: string[] }>(
    `${API_BASE}/api/web/session/_/providers/registered`,
  );
}

export async function analyzeConversationMessage(sessionToken: string, text: string, conversationId?: string, sender?: string) {
  return fetchWithRetry<{ ok: boolean; intelligence: Record<string, unknown>; memory: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/communication/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, conversation_id: conversationId || "", sender: sender || "lead" }),
    },
  );
}

export async function getConversationTimeline(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{ ok: boolean; events: Array<Record<string, unknown>>; total: number }>(
    `${API_BASE}/api/web/session/_/communication/${conversationId}/timeline`,
  );
}

export async function planWorkflow(sessionToken: string, objective: string) {
  return fetchWithRetry<{ ok: boolean; plan: Record<string, unknown>; alternative_plan: Record<string, unknown>; recommendation: string; confidence: string }>(
    `${API_BASE}/api/web/session/_/plan`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ objective, current_page: "dev-providers" }),
    },
  );
}

export type ProviderDiagnostics = {
  providers: Array<Record<string, unknown>>;
  provider_summary?: { total: number; healthy: number; offline: number; last_sync: string };
  conversation_intelligence?: Record<string, unknown>;
};

export async function getWorkspaceContext(sessionToken: string, conversationId?: string) {
  const params = new URLSearchParams();
  if (conversationId) params.set("conversation_id", conversationId);
  const qs = params.toString();
  return fetchWithRetry<Record<string, unknown>>(
    `${API_BASE}/api/web/session/_/workspace-context${qs ? '?' + qs : ''}`,
  );
}

export async function getCommunicationSummary(sessionToken: string, text: string) {
  return fetchWithRetry<{ ok: boolean; summary: string }>(
    `${API_BASE}/api/web/session/_/communication/summary`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
  );
}

export async function getCommunicationRecommend(sessionToken: string, text: string) {
  return fetchWithRetry<{ ok: boolean; recommendation: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/communication/recommend`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
  );
}


export async function listActiveJobs(sessionToken: string, userId = "") {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  let accessToken = "";
  try {
    accessToken = localStorage.getItem("loqi_access_token") || "";
  } catch { /* browser storage unavailable */ }
  return fetchWithRetry<{ jobs: JobResponse[] }>(
    `${API_BASE}/api/jobs${query}`,
    {
      headers: {
        Authorization: `Bearer ${sessionToken}`,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      timeout: 5000,
      retries: 0,
    },
  );
}

// ── Outbound API ──

export async function outboundCreateDraft(sessionToken: string, payload: Record<string, unknown>) {
  return fetchWithRetry<{ ok: boolean; draft: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/outbound/drafts`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
  );
}

export async function outboundUpdateDraft(sessionToken: string, draftId: string, payload: Record<string, unknown>) {
  return fetchWithRetry<{ ok: boolean; draft: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
  );
}

export async function outboundDeleteDraft(sessionToken: string, draftId: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}?provider_id=${encodeURIComponent(providerId)}`,
    { method: "DELETE" },
  );
}

export async function outboundSend(sessionToken: string, payload: Record<string, unknown>) {
  return fetchWithRetry<{ ok: boolean; send_result?: Record<string, unknown>; error?: string }>(
    `${API_BASE}/api/web/session/_/outbound/send`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
  );
}

export async function outboundSchedule(sessionToken: string, payload: Record<string, unknown>) {
  return fetchWithRetry<{ ok: boolean; schedule_id?: string; error?: string }>(
    `${API_BASE}/api/web/session/_/outbound/schedule`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
  );
}

export async function outboundCancelSchedule(sessionToken: string, scheduleId: string, providerId: string) {
  return fetchWithRetry<{ ok: boolean }>(
    `${API_BASE}/api/web/session/_/outbound/schedule/${scheduleId}?provider_id=${encodeURIComponent(providerId)}`,
    { method: "DELETE" },
  );
}

export async function outboundListDrafts(sessionToken: string, providerId?: string) {
  const params = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : '';
  return fetchWithRetry<{ ok: boolean; drafts: Record<string, unknown>[]; total: number }>(
    `${API_BASE}/api/web/session/_/outbound/drafts${params}`,
  );
}

export async function outboundGetDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; draft: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}`,
  );
}

export async function outboundApproveDraft(sessionToken: string, draftId: string, auto = false) {
  const params = auto ? '?auto=true' : '';
  return fetchWithRetry<{ ok: boolean; draft: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}/approve${params}`,
    { method: "POST" },
  );
}

export async function outboundRejectDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; draft: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}/reject`,
    { method: "POST" },
  );
}

export async function outboundGetHistory(sessionToken: string, providerId?: string) {
  const params = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : '';
  return fetchWithRetry<{ ok: boolean; history: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/outbound/history${params}`,
  );
}

export async function outboundGetEvents(sessionToken: string, providerId?: string, after?: number) {
  const params = new URLSearchParams();
  if (providerId) params.set("provider_id", providerId);
  if (after !== undefined) params.set("after", String(after));
  const qs = params.toString();
  return fetchWithRetry<{ ok: boolean; events: Record<string, unknown>[]; latest_sequence: number }>(
    `${API_BASE}/api/web/session/_/outbound/events${qs ? '?' + qs : ''}`,
  );
}

export async function outboundGetDraftVersions(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; versions: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/outbound/drafts/${draftId}/versions`,
  );
}

export async function outboundApproveAll(sessionToken: string, auto = false) {
  return fetchWithRetry<{ ok: boolean; total: number; created: number; failed: number; results: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/outbound/approve-all`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ auto }) },
  );
}

export async function getCampaignLaunchProgress(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; launch_sent: number; launch_total: number; launch_complete: boolean }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/launch-progress`,
  );
}

export type CampaignTimelineEvent = {
  id?: string;
  type: string;
  timestamp: string;
  actor?: string;
  data?: Record<string, unknown>;
  sequence?: number;
};

export async function getCampaignTimeline(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; events: CampaignTimelineEvent[] }>(
    `${API_BASE}/api/web/session/_/campaigns/${campaignId}/timeline`,
  );
}

/* ─── Conversations (workspace) ─── */

export async function listConversations(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; conversations: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/conversations`,
  );
}

export async function getConversation(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{ ok: boolean; conversation: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}`,
  );
}

export async function getConversationEvents(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{ ok: boolean; events: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/timeline`,
  );
}

export async function getConversationMessages(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{ ok: boolean; messages: Record<string, unknown>[] }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/messages`,
  );
}

export async function getConversationReasoning(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{ ok: boolean; reasoning: Record<string, unknown> | null }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/reasoning`,
  );
}

export async function getConversationPlan(sessionToken: string, conversationId: string) {
  return fetchWithRetry<{
    ok: boolean;
    plan: Record<string, unknown> | null;
    graph: {
      nodes: Array<{ id: string; type: string; status: string; label: string; dependencies: string[]; approval: string }>;
      edges: Array<{ source: string; target: string }>;
    } | null;
    explainability: Record<string, unknown> | null;
    validation: {
      valid: boolean;
      issues: Array<{ severity: string; code: string; message: string; task_id: string }>;
      warnings: Array<{ severity: string; code: string; message: string; task_id: string }>;
    } | null;
  }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/plan`,
    { method: "POST", cache: "no-store" },
  );
}

export async function generateConversationReply(
  sessionToken: string,
  conversationId: string,
  payload: { styles?: string[]; variant_count?: number; instruction?: string; follow_up?: boolean },
) {
  return fetchWithRetry<{ ok: boolean; generation: Record<string, unknown> | null; reasoning: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/generate-reply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function sendConversationReply(
  sessionToken: string,
  conversationId: string,
  payload: {
    body: string;
    thread_id?: string;
    reply_to_message_id?: string;
    test_recipient?: string;
    test_recipient_name?: string;
  },
) {
  return fetchWithRetry<{
    ok: boolean;
    conversation_id?: string;
    status?: string;
    message_id?: string;
    external_message_id?: string;
  }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/reply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function sendConversationFollowUp(
  sessionToken: string,
  conversationId: string,
  payload: {
    body: string;
    thread_id?: string;
    test_recipient?: string;
    test_recipient_name?: string;
  },
) {
  return fetchWithRetry<{
    ok: boolean;
    conversation_id?: string;
    status?: string;
    message_id?: string;
    external_message_id?: string;
  }>(
    `${API_BASE}/api/web/session/_/conversations/${conversationId}/follow-up`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

/* ─── Knowledge Foundation ─── */

export type KnowledgeCategory = "company" | "icp" | "messaging" | "sales_offer";
export type KnowledgeItemSourceType =
  | "user_input"
  | "uploaded_document"
  | "imported_source"
  | "system_generated";
export type KnowledgeSourceType =
  | "user_input"
  | "uploaded_document"
  | "imported_source"
  | "system_generated";

export type KnowledgeItem = {
  id: string;
  workspace_id: string;
  category: KnowledgeCategory;
  title: string;
  summary: string;
  content: Record<string, unknown>;
  tags: string[];
  source_type: KnowledgeItemSourceType;
  source_id: string;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
};

export type KnowledgeSource = {
  id: string;
  workspace_id: string;
  title: string;
  source_type: KnowledgeSourceType;
  content: string;
  reference: string;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
};

export type KnowledgeItemPayload = {
  category: KnowledgeCategory;
  title: string;
  summary?: string;
  content?: Record<string, unknown>;
  tags?: string[];
  source_type?: KnowledgeItemSourceType;
  source_id?: string;
};

export type KnowledgeItemUpdate = Partial<Omit<KnowledgeItemPayload, "category">>;

export type KnowledgeSourcePayload = {
  title: string;
  source_type?: KnowledgeSourceType;
  content?: string;
  reference?: string;
  metadata?: Record<string, unknown>;
};

export type KnowledgeSourceUpdate = Partial<KnowledgeSourcePayload>;

export async function listKnowledge(
  sessionToken: string,
  params: { category?: KnowledgeCategory; q?: string } = {},
) {
  const query = new URLSearchParams();
  if (params.category) query.set("category", params.category);
  if (params.q) query.set("q", params.q);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return fetchWithRetry<{ ok: boolean; items: KnowledgeItem[] }>(
    `${API_BASE}/api/web/session/_/knowledge${suffix}`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function getKnowledgeItem(sessionToken: string, itemId: string) {
  return fetchWithRetry<{ ok: boolean; item: KnowledgeItem }>(
    `${API_BASE}/api/web/session/_/knowledge/${itemId}`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function createKnowledgeItem(
  sessionToken: string,
  payload: KnowledgeItemPayload,
) {
  return fetchWithRetry<{ ok: boolean; item: KnowledgeItem }>(
    `${API_BASE}/api/web/session/_/knowledge`,
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function updateKnowledgeItem(
  sessionToken: string,
  itemId: string,
  payload: KnowledgeItemUpdate,
) {
  return fetchWithRetry<{ ok: boolean; item: KnowledgeItem }>(
    `${API_BASE}/api/web/session/_/knowledge/${itemId}`,
    {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function archiveKnowledgeItem(sessionToken: string, itemId: string) {
  return fetchWithRetry<{ ok: boolean; item: KnowledgeItem }>(
    `${API_BASE}/api/web/session/_/knowledge/${itemId}`,
    { method: "DELETE", headers: authHeaders() },
  );
}

export async function listKnowledgeSources(sessionToken: string, q = "") {
  const suffix = q ? `?q=${encodeURIComponent(q)}` : "";
  return fetchWithRetry<{ ok: boolean; sources: KnowledgeSource[] }>(
    `${API_BASE}/api/web/session/_/knowledge/sources${suffix}`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function createKnowledgeSource(
  sessionToken: string,
  payload: KnowledgeSourcePayload,
) {
  return fetchWithRetry<{ ok: boolean; source: KnowledgeSource }>(
    `${API_BASE}/api/web/session/_/knowledge/sources`,
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function updateKnowledgeSource(
  sessionToken: string,
  sourceId: string,
  payload: KnowledgeSourceUpdate,
) {
  return fetchWithRetry<{ ok: boolean; source: KnowledgeSource }>(
    `${API_BASE}/api/web/session/_/knowledge/sources/${sourceId}`,
    {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function archiveKnowledgeSource(sessionToken: string, sourceId: string) {
  return fetchWithRetry<{ ok: boolean; source: KnowledgeSource }>(
    `${API_BASE}/api/web/session/_/knowledge/sources/${sourceId}`,
    {
      method: "DELETE",
      headers: authHeaders(),
    },
  );
}

/* ─── Strategic Intelligence ─── */

export type StrategicEvidence = {
  signal_id: string;
  signal_type: string;
  source_type: string;
  entity_type: string;
  entity_id: string;
  campaign_id: string;
  lead_id: string;
  conversation_id: string;
  message_id: string;
  observed_at: string;
  value: unknown;
  metadata: Record<string, unknown>;
};

export type StrategicUpdate = {
  id: string;
  workspace_id: string;
  pattern_key: string;
  title: string;
  summary: string;
  update_type: string;
  status: string;
  confidence: string;
  observed_at: string;
  observation: string;
  interpretation: string;
  recommendation: string;
  structured_analysis: Record<string, unknown>;
  evidence: StrategicEvidence[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export async function listStrategicUpdates(
  sessionToken: string,
  params: { update_type?: string; confidence?: string; q?: string } = {},
) {
  const query = new URLSearchParams();
  if (params.update_type) query.set("update_type", params.update_type);
  if (params.confidence) query.set("confidence", params.confidence);
  if (params.q) query.set("q", params.q);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return fetchWithRetry<{ ok: boolean; updates: StrategicUpdate[]; last_analyzed: string | null }>(
    `${API_BASE}/api/web/session/_/strategic-updates${suffix}`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function refreshStrategicUpdates(sessionToken: string) {
  return fetchWithRetry<{
    ok: boolean;
    updates: StrategicUpdate[];
    new_updates: number;
    refreshed_updates: number;
    patterns_found: number;
    last_analyzed: string;
    activity_summary: Record<string, unknown>;
  }>(
    `${API_BASE}/api/web/session/_/strategic-updates/refresh`,
    { method: "POST", headers: authHeaders() },
  );
}

export async function getStrategicUpdate(sessionToken: string, updateId: string) {
  return fetchWithRetry<{ ok: boolean; update: StrategicUpdate }>(
    `${API_BASE}/api/web/session/_/strategic-updates/${updateId}`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function archiveStrategicUpdate(sessionToken: string, updateId: string) {
  return fetchWithRetry<{ ok: boolean; update: StrategicUpdate }>(
    `${API_BASE}/api/web/session/_/strategic-updates/${updateId}`,
    { method: "DELETE", headers: authHeaders() },
  );
}

export type StrategicAction = {
  id: string;
  workspace_id: string;
  strategic_update_id: string;
  action_type: "update_messaging" | "refine_icp" | "create_campaign" | string;
  status: "proposed" | "approved" | "executing" | "completed" | "failed" | "dismissed" | string;
  proposal: Record<string, unknown>;
  created_by: string;
  created_at: string;
  approved_at: string | null;
  executed_at: string | null;
  dismissed_at: string | null;
  error: string;
  result: Record<string, unknown>;
  metadata: Record<string, unknown>;
  updated_at: string;
};

export async function listStrategicActions(sessionToken: string, updateId: string) {
  return fetchWithRetry<{ ok: boolean; actions: StrategicAction[] }>(
    `${API_BASE}/api/web/session/_/strategic-updates/${updateId}/actions`,
    { cache: "no-store", headers: authHeaders() },
  );
}

export async function proposeStrategicAction(
  sessionToken: string,
  updateId: string,
  actionType: StrategicAction["action_type"],
) {
  return fetchWithRetry<{ ok: boolean; action: StrategicAction }>(
    `${API_BASE}/api/web/session/_/strategic-updates/${updateId}/actions`,
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ action_type: actionType }),
    },
  );
}

export async function approveStrategicAction(sessionToken: string, actionId: string) {
  return fetchWithRetry<{ ok: boolean; action: StrategicAction }>(
    `${API_BASE}/api/web/session/_/strategic-actions/${actionId}/approve`,
    { method: "POST", headers: authHeaders() },
  );
}

export async function dismissStrategicAction(sessionToken: string, actionId: string) {
  return fetchWithRetry<{ ok: boolean; action: StrategicAction }>(
    `${API_BASE}/api/web/session/_/strategic-actions/${actionId}/dismiss`,
    { method: "POST", headers: authHeaders() },
  );
}

export async function refineStrategicAction(
  sessionToken: string,
  actionId: string,
  changes: Record<string, unknown>,
) {
  return fetchWithRetry<{ ok: boolean; action: StrategicAction }>(
    `${API_BASE}/api/web/session/_/strategic-actions/${actionId}/refine`,
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ changes }),
    },
  );
}

export async function executeStrategicAction(sessionToken: string, actionId: string) {
  return fetchWithRetry<{ ok: boolean; action: StrategicAction }>(
    `${API_BASE}/api/web/session/_/strategic-actions/${actionId}/execute`,
    { method: "POST", headers: authHeaders() },
  );
}

/* ─── Phase 11: Mission Control Briefing ─── */

export type IntentionCard = {
  id: string;
  title: string;
  summary: string;
  priority: string;
  confidence: number;
  evidence: Array<{ reason_code: string; confidence: number; source: string; detail: string }>;
  recommended_action: string;
  related_campaign: string | null;
  related_lead: string | null;
  reason_code: string;
};

export type BriefingSection = {
  greeting: string;
  lines: string[];
  suggestion: string;
  overall_summary: string;
  primary_focus: string;
  top_recommendation: string;
};

export type HealthSummary = {
  overall_health: string;
  pipeline_velocity: string;
  bottlenecks: string[];
  provider_health: Array<Record<string, unknown>>;
  confidence_score: number;
  campaigns_ready: number;
  campaigns_waiting: number;
  draft_backlog: number;
  details: Record<string, unknown>;
};

export type TimelineEvent = {
  id: string;
  timestamp: string;
  type: string;
  description: string;
  category: string;
  actor: string;
  metadata: Record<string, unknown>;
};

export type BriefingResponse = {
  ok: boolean;
  briefing: BriefingSection;
  top_priorities: IntentionCard[];
  waiting_on_you: IntentionCard[];
  loqi_handled: IntentionCard[];
  upcoming: IntentionCard[];
  workspace_health: HealthSummary;
  timeline: TimelineEvent[];
  all_intentions: IntentionCard[];
};

export async function getBriefing(sessionToken: string, onboardingUserId = "") {
  return fetchWithRetry<BriefingResponse>(
    `${API_BASE}/api/web/session/_/briefing?onboarding_user_id=${encodeURIComponent(onboardingUserId)}`,
    { headers: authHeaders() },
  );
}
