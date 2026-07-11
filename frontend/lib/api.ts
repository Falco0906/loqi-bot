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

  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) {
      const delay = attempt === 1 ? 500 : 1000;
      await new Promise((r) => setTimeout(r, delay));
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(url, {
        method: options.method || "GET",
        headers: options.headers,
        body: options.body,
        cache: options.cache,
        signal: options.signal || controller.signal,
      });

      clearTimeout(timeoutId);

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
) {
  return fetchWithRetry<{ ok: boolean; draft: unknown }>(
    `${API_BASE}/api/web/session/${sessionToken}/drafts/${draftId}/refine`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edit_request: editRequest, previous_message: previousMessage, lead }),
    },
  );
}

export async function approveDraft(sessionToken: string, draftId: string) {
  return fetchWithRetry<{ ok: boolean; draft: unknown }>(
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
