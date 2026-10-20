/** Actual Loqi UI, explicitly configured frontend, direct native backend HTTP.
 * API/OPTIONS never match a route handler. No API rewriting or Node bridge.
 */
import { test as base, expect, type Request } from "@playwright/test";
import { backend, frontend, workspace, session } from "./native-discovery.fixture";

export const workspaceB = "20000000-0000-4000-8000-000000000002";
const allowedPaths = new Set(["/health", "/__loqi_test/identity", "/__loqi_test/fault", "/api/v1/auth/me",
  "/api/v1/auth/refresh", "/api/v1/beta/features", "/api/events/stream", "/api/discoveries",
  "/api/web/session/_/workspaces", "/api/web/session/_/workspaces/select", "/api/web/session/_/leads"]);
type RequestRecord = { method: string; path: string; url: URL; workspace: string };
type LeadRead = { url: URL; requestIndex: number; workspace: string; status: number;
  body: { total: number; leads: Array<{ id: string }> } };
export type LargeUI = { requests: RequestRecord[]; reads: LeadRead[]; flushReads: () => Promise<void>;
  call: (path: string, body?: unknown) => Promise<any> };

export const test = base.extend<{ largeUI: LargeUI }>({
  largeUI: [async ({ context, page, baseURL, browserName }, use) => {
    if (browserName !== "firefox" || baseURL !== frontend || process.env.LOQI_RUN_DISCOVERY_HTTP !== "1"
      || process.env.LOQI_ISOLATED_BACKEND_URL !== backend || process.env.NEXT_PUBLIC_LOQI_API_BASE_URL !== backend) {
      throw new Error("Explicit Firefox/frontend/backend settings required; frontend must be built for port 19876");
    }
    const runId = process.env.LOQI_ISOLATED_BACKEND_RUN_ID || "";
    if (!/^[0-9a-f-]{36}$/.test(runId)) throw new Error("Approve the new large-profile run UUID");
    const blocked: string[] = [];
    const requests: RequestRecord[] = [];
    const reads: LeadRead[] = [];
    const pending: Promise<void>[] = [];
    const requestIndices = new WeakMap<Request, number>();
    const apiAllowed = (url: URL) => url.origin === backend && !url.username && !url.password
      && (allowedPaths.has(url.pathname) || /^\/api\/discoveries\/[0-9a-f-]{36}$/.test(url.pathname));
    const assetAllowed = (url: URL) => url.origin === frontend && !url.username && !url.password && !url.pathname.startsWith("/api/");
    await context.setExtraHTTPHeaders({ "X-Loqi-Test-Run-Id": runId });
    await context.routeWebSocket("**/*", socket => socket.close());
    await context.route(url => !apiAllowed(url) && !assetAllowed(url), async route => {
      blocked.push(`${route.request().method()} ${new URL(route.request().url()).origin}${new URL(route.request().url()).pathname}`);
      await route.abort("blockedbyclient");
    });
    // Only real frontend HTML is relayed, unchanged except a restrictive CSP.
    // This prevents the app's external font/preconnect tags from making egress.
    // Tested API requests and their OPTIONS do not match this document handler.
    await context.route(url => assetAllowed(url) && ["/discovery", "/discovery/history", "/contacts"].includes(url.pathname), async route => {
      if (route.request().method() !== "GET") { blocked.push("Unexpected frontend mutation"); await route.abort(); return; }
      if (!route.request().isNavigationRequest()) { await route.continue(); return; }
      const response = await route.fetch({ maxRedirects: 0 });
      if (response.status() !== 200) throw new Error("Approved frontend document unavailable");
      await route.fulfill({ response, headers: { ...response.headers(),
        "content-security-policy": `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' ${backend}; frame-src 'none'`,
      } });
    });
    context.on("request", request => {
      const url = new URL(request.url());
      if (apiAllowed(url)) {
        requestIndices.set(request, requests.length);
        requests.push({ method: request.method(), path: url.pathname, url,
          workspace: request.headers()["x-workspace-id"] || "" });
      }
    });
    page.on("response", response => {
      const url = new URL(response.url());
      if (apiAllowed(url) && url.pathname === "/api/web/session/_/leads"
        && response.request().method() === "GET" && response.status() === 200) {
        const requestIndex = requestIndices.get(response.request());
        if (requestIndex === undefined) throw new Error("Native lead response has no observed request");
        pending.push(response.json().then(body => { reads.push({ url, body, requestIndex,
          workspace: requests[requestIndex].workspace, status: response.status() }); })
          .catch(() => { blocked.push("Could not inspect native lead response"); }));
      }
    });
    // Native top-level identity probe before mounting Loqi or using credentials.
    const probe = await page.goto(`${backend}/__loqi_test/identity`);
    const identity = await probe!.json();
    if (probe!.status() !== 200 || identity.marker !== "loqi-isolated-discovery-v1" || identity.run_id !== runId
      || identity.persistence !== "synthetic-memory" || identity.outbound_blocked !== true || identity.profile !== "large"
      || JSON.stringify(identity.fixture_counts) !== JSON.stringify({ workspace_a: 604, workspace_b: 2, foreign: 1, total: 607 })) {
      throw new Error("Large-profile identity mismatch; do not run against the small backend");
    }
    await context.addInitScript(({ session }) => {
      localStorage.setItem("loqi_user_id", "10000000-0000-4000-8000-000000000001");
      localStorage.setItem("loqi_org_id", "10000000-0000-4000-8000-000000000002");
      for (const key of ["loqi_access_token", "loqi_refresh_token", "loqi_active_session_token"]) localStorage.setItem(key, session);
    }, { session });
    const call: LargeUI["call"] = async (path, body) => {
      const url = new URL(path, backend);
      if (!path.startsWith("/") || path.startsWith("//") || !apiAllowed(url)) throw new Error("Unapproved native API call");
      return page.evaluate(async ({ url, body, session, workspace }) => {
        const response = await fetch(url, { method: body === undefined ? "GET" : "POST", credentials: "omit", redirect: "error",
          headers: { authorization: `Bearer ${session}`, "x-workspace-id": workspace, ...(body === undefined ? {} : { "content-type": "application/json" }) },
          body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(8000) });
        if (!response.ok) throw new Error(`Synthetic HTTP ${response.status}`);
        return response.json();
      }, { url: url.href, body, session, workspace });
    };
    const flushReads = async () => { await Promise.all(pending); };
    try { await use({ requests, reads, flushReads, call }); }
    finally {
      await Promise.all(pending);
      expect(blocked, "No fallback, external destination or unexpected API is allowed").toEqual([]);
    }
  }, { auto: true }],
});
test.use({ serviceWorkers: "block", launchOptions: { firefoxUserPrefs: {
  "network.dns.disablePrefetch": true, "network.prefetch-next": false,
  "network.predictor.enabled": false, "network.http.speculative-parallel-limit": 0,
} } });
export { expect, workspace, backend };
