import type { LeadIntelligence, LoqiMessage, LoqiSessionSummary } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_LOQI_API_BASE_URL || "http://127.0.0.1:10000";

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

async function fetchWithRetry<T>(
  url: string,
  options: FetchOptions = {},
): Promise<T> {
  const timeout = options.timeout ?? 10000;
  const retries = options.retries ?? 2;
  let lastError: Error | null = null;
  const _start = Date.now();
  console.log(`[FETCH_TRACE] fetchWithRetry | url=${url.split('/').pop()} | timeout=${timeout}ms | retries=${retries} | started`);

  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) {
      const delay = attempt === 1 ? 500 : 1000;
      console.log(`[FETCH_TRACE] fetchWithRetry | attempt=${attempt} | backing off ${delay}ms`);
      await new Promise((r) => setTimeout(r, delay));
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      console.log(`[FETCH_TRACE] fetchWithRetry | attempt=${attempt} | fetch started`);
      const response = await fetch(url, {
        method: options.method || "GET",
        headers: options.headers,
        body: options.body,
        cache: options.cache,
        signal: options.signal || controller.signal,
      });

      clearTimeout(timeoutId);
      console.log(`[FETCH_TRACE] fetchWithRetry | attempt=${attempt} | fetch DONE | status=${response.status} | duration=${Date.now()-_start}ms`);

      if (!response.ok) {
        const text = await response.text();
        throw new ApiError(
          text || `Request failed with ${response.status}`,
          response.status,
        );
      }

      return (await response.json()) as T;
    } catch (err) {
      clearTimeout(timeoutId);
      lastError = err as Error;
      console.log(`[FETCH_TRACE] fetchWithRetry | attempt=${attempt} | CATCH | err=${err instanceof Error ? err.name : 'unknown'} | duration=${Date.now()-_start}ms`);

      if (err instanceof ApiError) throw err;

      if (err instanceof DOMException && err.name === "AbortError") {
        lastError = new TimeoutError();
      } else if (!(err instanceof TimeoutError)) {
        lastError = new NetworkError(
          err instanceof Error ? err.message : "Failed to fetch",
        );
      }
    }
  }

  console.log(`[FETCH_TRACE] fetchWithRetry | EXHAUSTED | throwing ${lastError instanceof Error ? lastError.name : 'unknown'} | duration=${Date.now()-_start}ms`);
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
  return fetchWithRetry<{
    ok: boolean;
    session_token: string;
    gmail_connected: boolean;
  }>(`${API_BASE}/api/web/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function getSession(sessionToken: string) {
  return fetchWithRetry<LoqiSessionSummary>(
    `${API_BASE}/api/web/session/${sessionToken}`,
    { cache: "no-store" },
  );
}

export async function sendMessage(sessionToken: string, text: string) {
  return fetchWithRetry<{ ok: boolean; messages: LoqiMessage[] }>(
    `${API_BASE}/api/web/session/${sessionToken}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  },
) {
  return fetchWithRetry<{
    ok: boolean;
    messages: LoqiMessage[];
    events: unknown[];
    session_token?: string;
  }>(
    `${API_BASE}/api/web/session/${sessionToken}/messages`,
    {
      method: "POST",
      timeout: 20000,
      retries: 1,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: params.text,
        copilot: {
          current_page: params.currentPage,
          page_context: params.pageContext,
          available_actions: params.availableActions,
        },
      }),
    },
  );
}

export async function selectLead(sessionToken: string, index: number) {
  return fetchWithRetry<{ ok: boolean; messages: LoqiMessage[] }>(
    `${API_BASE}/api/web/session/${sessionToken}/select-lead`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    },
  );
}

export async function previewLead(sessionToken: string, index: number) {
  return fetchWithRetry<{ ok: boolean; lead_intelligence: LeadIntelligence }>(
    `${API_BASE}/api/web/session/${sessionToken}/preview-lead`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    },
  );
}

export async function getGmailStatus(sessionToken: string) {
  return fetchWithRetry<{
    ok: boolean;
    gmail_connected: boolean;
    connect_url: string;
  }>(`${API_BASE}/api/web/session/${sessionToken}/gmail`, {
    cache: "no-store",
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
  }>(`${API_BASE}/api/web/session/${sessionToken}/analyze-campaigns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ leads }),
  });
}

/* ─── Batch discovery ─── */

export async function batchDraft(sessionToken: string, leads: unknown[], campaignId?: string) {
  return fetchWithRetry<{ ok: boolean; batch_id: string; total: number }>(
    `${API_BASE}/api/web/session/${sessionToken}/batch-draft`,
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
  }>(`${API_BASE}/api/web/session/${sessionToken}/batch-status/${batchId}`);
}

/* ─── Draft CRUD ─── */

export async function listDrafts(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; drafts: unknown[] }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts`,
  );
}

export async function updateDraft(sessionToken: string, draftId: string, text: string) {
  return fetchWithRetry<{ ok: boolean; draft: unknown }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts/${draftId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
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
  return fetchWithRetry<{ ok: boolean; draft: { id: string; text: string; status: string }; rewritten_text?: string }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts/${draftId}/refine`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

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
  return fetchWithRetry<{ ok: boolean; analysis: DraftAnalysis | null; error?: string }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
    `${API_BASE}/api/web/session/${sessionToken}/drafts/ask`,
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
    pending_drafts?: number;
  }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts/${draftId}/approve`,
    { method: "POST" },
  );
}

/* ─── Campaigns ─── */

export async function saveCampaign(
  sessionToken: string,
  name: string,
  searchQuery?: string,
  leadCount?: number,
  strategy?: unknown,
  status?: string,
  leads?: unknown[],
) {
  return fetchWithRetry<{ ok: boolean; campaign: unknown }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        search_query: searchQuery,
        lead_count: leadCount,
        strategy,
        status: status || "planning",
        leads,
      }),
    },
  );
}

export async function listCampaigns(sessionToken: string) {
  return fetchWithRetry<{ ok: boolean; campaigns: Array<Record<string, unknown>> }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns`,
  );
}

export async function getCampaign(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}`,
  );
}

export async function updateCampaign(
  sessionToken: string,
  campaignId: string,
  updates: { name?: string; status?: string },
) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    },
  );
}

export async function archiveCampaign(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; campaign: Record<string, unknown> }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}`,
    { method: "DELETE" },
  );
}

export async function listCampaignDrafts(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; drafts: unknown[] }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}/drafts`,
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
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/summary`,
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
};

export type MCRecommendation = {
  type: string;
  text: string;
  action: string;
  link: string;
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

export type MCSummary = {
  ok: boolean;
  campaigns: MCCampaign[];
  draft_counts: { pending: number; approved: number; total: number };
  needs_attention: NeedAttentionItem[];
  live_activity: RecentOutcome[];
  campaign_count: number;
  active_jobs: unknown[];
  recommendations: MCRecommendation[];
  kpis: {
    estimated_reply_rate: number;
    avg_qualification_score: number;
    pending_reviews: number;
    campaigns_ready: number;
  };
  total_leads: number;
};

export async function getMissionControl(sessionToken: string) {
  return fetchWithRetry<MCSummary>(
    `${API_BASE}/api/web/session/${sessionToken}/mission-control`,
  );
}

/* ─── Campaign Draft Generation ─── */

export async function generateCampaignDrafts(sessionToken: string, campaignId: string) {
  return fetchWithRetry<{ ok: boolean; batch_id: string; total: number }>(
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}/generate-drafts`,
    { method: "POST" },
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
    `${API_BASE}/api/web/session/${sessionToken}/campaigns/${campaignId}/generation-status`,
  );
}

/* ─── Export ─── */

export function getExportCsvUrl(sessionToken: string) {
  return `${API_BASE}/api/web/session/${sessionToken}/export-csv`;
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

export async function startSearchJob(sessionToken: string, query: string) {
  return fetchWithRetry<{ job_id: string; status: string }>(
    `${API_BASE}/api/jobs/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-session-token": sessionToken },
      body: JSON.stringify({ query }),
      timeout: 5000,
      retries: 0,
    },
  );
}

export async function getJob(jobId: string) {
  return fetchWithRetry<JobResponse>(
    `${API_BASE}/api/jobs/${jobId}`,
    { timeout: 5000, retries: 0 },
  );
}

export async function getJobResults(jobId: string) {
  return fetchWithRetry<{ ok: boolean; leads: Record<string, unknown>[] }>(
    `${API_BASE}/api/jobs/${jobId}/results`,
    { timeout: 5000, retries: 0 },
  );
}

export async function listActiveJobs(sessionToken: string) {
  return fetchWithRetry<{ jobs: JobResponse[] }>(
    `${API_BASE}/api/jobs`,
    {
      headers: { "x-session-token": sessionToken },
      timeout: 5000,
      retries: 0,
    },
  );
}
