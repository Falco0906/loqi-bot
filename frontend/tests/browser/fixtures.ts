import { test as base, expect, type BrowserContext, type Route } from "@playwright/test";

export const ids = {
  user: "10000000-0000-4000-8000-000000000001",
  org: "10000000-0000-4000-8000-000000000002",
  a: "20000000-0000-4000-8000-000000000001",
  b: "20000000-0000-4000-8000-000000000002",
  campaign: "30000000-0000-4000-8000-000000000001",
  draft: "40000000-0000-4000-8000-000000000001",
  run: "50000000-0000-4000-8000-000000000001",
  job: "60000000-0000-4000-8000-000000000001",
};
export function lead(index: number, workspace = ids.a) {
  return {
    id: `70000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    workspace_id: workspace, first_name: workspace === ids.b ? "Beta" : "Ada",
    last_name: `Person ${index}`, email: `person${index}@example.invalid`,
    company: workspace === ids.b ? "Beta Company" : "Acme", title: "Founder",
    website: "https://example.invalid", location: "United States", industry: "SaaS",
    source: "workspace", source_label: "CSV import", source_provenance: ["CSV import"],
  };
}
type Reply = { status?: number; json: unknown };
type Call = { method: string; path: string; workspace: string; body: any; url: URL };

/** Test-owned in-memory backend simulator, never a database or provider client. */
export class MockApi {
  calls: Call[] = [];
  blocked: string[] = [];
  rows = [lead(1), lead(2)];
  count = 2;
  listFailure = false;
  workspaceListFailure = false;
  workspaceListEmpty = false;
  generationFailure = false;
  override?: (call: Call) => Promise<Reply | undefined>;
  campaign: any = { id: ids.campaign, name: "Review campaign", status: "planning", leads: [], lead_count: 0, strategy: null };
  draft: any = { id: ids.draft, campaign_id: ids.campaign, subject: "Initial subject", text: "Initial message", status: "pending", lead: { ...lead(1), name: "Ada Person 1" } };
  generations = new Map<string, any>();
  runQuery = "";

  analysis(selected: string[]) {
    return { ok: true, business_guidance: { note: "Guidance is not prospect evidence.", items: [], source_ids: [] }, results: selected.map(id => ({
      lead: this.rows.find(row => row.id === id) || { ...lead(1), id }, status: "completed",
      facts: [{ label: "Company", value: "Acme", source: "canonical" }], observed_signals: [],
      derived_assessment: { priority: "medium", icp_fit: 60, why_this_lead: ["Recorded role matches"], recommended_approach: "Ask a conservative question" },
    })) };
  }

  async reply(call: Call): Promise<Reply | undefined> {
    const custom = await this.override?.(call);
    if (custom) return custom;
    const { path, method, body, workspace, url } = call;
    if (path === "/health") return { json: { status: "ok" } };
    if (path === "/api/v1/auth/refresh") return { json: { access_token: "synthetic-access", refresh_token: "synthetic-refresh", user_id: ids.user, org_id: ids.org } };
    if (path === "/api/v1/auth/me") return { json: { id: ids.user, display_name: "Offline Operator", email: "operator@example.invalid", onboarding_complete: true, organization: { id: ids.org, name: "Offline", role: "owner" } } };
    if (path === "/api/v1/beta/features") return { json: { ok: true, features: { lead_database: true, csv_import: true, lead_search: true, lead_filtering: true, lead_selection: true, lead_analysis: true, strategy_generation: true, outreach_generation: true } } };
    // Explicit mocked rejection avoids SSE reconnection loops; no real stream.
    if (path === "/api/events/stream") return { status: 403, json: { detail: "Offline stream disabled" } };
    if (path === "/api/web/session/_/workspaces") {
      if (this.workspaceListFailure) return { status: 503, json: { detail: "Fixture workspace service unavailable" } };
      if (this.workspaceListEmpty) return { json: { ok: true, workspaces: [] } };
      return { json: { ok: true, workspaces: [{ id: ids.a, name: "Alpha Workspace" }, { id: ids.b, name: "Beta Workspace" }] } };
    }
    if (path === "/api/web/session/_/workspaces/select" && method === "POST") {
      const selected = workspace === ids.a ? "Alpha Workspace" : workspace === ids.b ? "Beta Workspace" : "";
      return selected
        ? { json: { ok: true, workspace: { id: workspace, name: selected } } }
        : { status: 404, json: { detail: "Workspace not found" } };
    }
    if (path.startsWith("/api/web/session/_/") && ![ids.a, ids.b].includes(workspace)) return { status: 403, json: { detail: "Workspace is inaccessible" } };
    const root = "/api/web/session/_";
    if (path === `${root}/leads` && method === "GET") {
      if (this.listFailure) return { status: 503, json: { detail: "Fixture database unavailable" } };
      let rows = workspace === ids.b ? [lead(101, ids.b)] : this.rows;
      for (const key of ["location", "industry", "company", "title"] as const) {
        const value = url.searchParams.get(key);
        if (value) rows = rows.filter(row => row[key].toLowerCase().includes(value.toLowerCase()));
      }
      const page = Number(url.searchParams.get("page") || 1);
      return { json: { ok: true, leads: rows.slice((page - 1) * 50, page * 50), total: rows.length, page, page_size: 50 } };
    }
    if (path === `${root}/leads/csv-preview`) {
      const row = { first_name: "Ada", last_name: "Person 1", email: "person1@example.invalid", company: "Acme", title: "Founder" };
      return { json: { ok: true, headers: Object.keys(row), mapping: Object.fromEntries(Object.keys(row).map(key => [key, key])), unmapped_columns: [], total_rows: 1, valid_rows: 1, invalid_rows: [], rows: [{ row: 2, lead: row }], preview: [{ row: 2, lead: row }] } };
    }
    if (path === `${root}/leads/csv-import`) { this.rows = [lead(1)]; this.count = 1; return { json: { ok: true, imported: 1, duplicates: [], invalid: [] } }; }
    if (path === `${root}/leads/analyze`) return { json: this.analysis(body.lead_ids) };
    if (path === `${root}/leads/generate-strategy`) {
      if (this.generationFailure) return { status: 503, json: { detail: "Fixture generation unavailable" } };
      const result = { ok: true, job_id: ids.job, lead_ids: body.lead_ids, status: "completed", stage: "Complete", progress: 100, analysis: this.analysis(body.lead_ids), results: body.lead_ids.map((id: string) => ({ lead_id: id, status: "completed", strategy: { relevance_summary: "Recorded founder role", recommended_angle: "Ask about priorities", key_message: "A conservative introduction", things_to_avoid: ["Unsupported pain claims"], next_action: "Review manually" }, outreach: { subject: "A question", body: "Hello, may I share a short introduction?" }, evidence_used: [{ source_type: "canonical_fact", statement: "Recorded founder role" }] })) };
      this.generations.set(body.request_key, result);
      return { json: { ...result, status: "queued", results: [] } };
    }
    if (path === `${root}/leads/generation`) return this.generations.has(url.searchParams.get("request_key") || "") ? { json: this.generations.get(url.searchParams.get("request_key") || "") } : { status: 404, json: { detail: "Generation not found" } };
    if (path === "/api/discoveries" && method === "POST") { this.runQuery = body.query; return { json: { ok: true, discovery_id: ids.run, job_id: ids.job, status: "completed" } }; }
    if (path === "/api/discoveries" && method === "GET") return { json: { ok: true, discoveries: [] } };
    if (path === `/api/discoveries/${ids.run}`) return { json: { ok: true, discovery: { id: ids.run, query: this.runQuery, status: "completed", summary: { lead_count: this.count }, metadata: {}, filters: [], provider_provenance: {}, discovery_companies: [], discovery_leads: [], created_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:01Z" } } };
    if (path === `${root}/campaigns/summary` || (path === `${root}/campaigns` && method === "GET")) return { json: { ok: true, campaigns: workspace === ids.a ? [this.campaign] : [] } };
    if (path === `${root}/campaigns` && method === "POST") { this.campaign = { ...this.campaign, name: body.name, leads: body.leads || [], lead_count: body.leads?.length || 0 }; return { json: { ok: true, campaign: this.campaign } }; }
    if (path === `${root}/campaigns/${ids.campaign}`) return workspace === ids.a ? { json: { ok: true, campaign: this.campaign } } : { status: 404, json: { detail: "Campaign not found" } };
    if (path === `${root}/campaigns/${ids.campaign}/leads` && method === "POST") { this.campaign.leads.push(body.lead || body); return { json: { ok: true, campaign: this.campaign } }; }
    if (path === `${root}/campaigns/${ids.campaign}/drafts`) return { json: { ok: true, drafts: workspace === ids.a ? [this.draft] : [] } };
    if (path === `${root}/drafts` && method === "GET") return { json: { ok: true, drafts: workspace === ids.a ? [this.draft] : [] } };
    if (path === `${root}/drafts/${ids.draft}` && method === "PUT") {
      const match = /^Subject: ([^\n]*)\n\n([\s\S]*)$/.exec(body.text);
      if (!match) return { status: 422, json: { detail: "Expected subject and body" } };
      this.draft = { ...this.draft, subject: match[1], text: match[2], status: "pending" };
      return { json: { ok: true, draft: this.draft } };
    }
    return undefined;
  }
}

export async function isolate(context: BrowserContext, api: MockApi, localOrigin?: string) {
  await context.routeWebSocket("**/*", socket => {
    const url = new URL(socket.url());
    if (!(url.origin.replace(/^ws/, "http") === localOrigin && url.pathname === "/_next/webpack-hmr")) api.blocked.push("WebSocket");
    socket.close();
  });
  await context.route("**/*", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    // Fonts are intentionally stubbed offline, never downloaded.
    if (["fonts.googleapis.com", "fonts.gstatic.com"].includes(url.hostname)) { await route.fulfill({ body: "", contentType: "text/css" }); return; }
    if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
          "access-control-allow-headers": "content-type, authorization, x-workspace-id",
        } });
        return;
      }
      const call: Call = { method: request.method(), path: url.pathname, url, workspace: request.headers()["x-workspace-id"] || "", body: request.postData() ? JSON.parse(request.postData()!) : {} };
      api.calls.push(call);
      const reply = await api.reply(call);
      if (reply) { await route.fulfill({ status: reply.status || 200, json: reply.json, headers: { "access-control-allow-origin": "*" } }); return; }
    } else if (url.origin === localOrigin && request.method() === "GET" && ["document", "script", "stylesheet", "image", "font", "fetch", "other"].includes(request.resourceType())) {
      // Only the user-managed Next frontend may receive unmocked requests.
      await route.continue(); return;
    }
    api.blocked.push(`${request.method()} ${url.origin}${url.pathname}`);
    await route.abort("blockedbyclient");
  });
  await context.addInitScript(({ user, org }) => {
    localStorage.setItem("loqi_access_token", "synthetic-access");
    localStorage.setItem("loqi_refresh_token", "synthetic-refresh");
    localStorage.setItem("loqi_user_id", user);
    localStorage.setItem("loqi_org_id", org);
    localStorage.setItem("loqi_active_session_token", "synthetic-web-session");
  }, ids);
}

export const test = base.extend<{ api: MockApi }>({
  api: [async ({ context, baseURL, page }, use, testInfo) => {
    if (!baseURL) throw new Error("Start the frontend yourself, then set LOQI_BROWSER_BASE_URL to its loopback origin. No server is started by this runner.");
    const api = new MockApi();
    const consoleErrors: string[] = [];
    page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("pageerror", error => consoleErrors.push(error.message));
    await isolate(context, api, new URL(baseURL).origin);
    await use(api);
    expect(api.blocked, "Every request must be a declared mock or local frontend asset").toEqual([]);
    if (consoleErrors.length) await testInfo.attach("browser-console-errors", { body: Buffer.from(consoleErrors.join("\n")), contentType: "text/plain" });
    expect(consoleErrors, "Browser console and page errors").toEqual([]);
  }, { auto: true }],
});
export { expect };
