/** Native Firefox transport: only the static document is fulfilled by Playwright.
 * Approved backend URLs deliberately match NO route handler or Node HTTP bridge.
 */
import { test as base, expect } from "@playwright/test";
import { createRequire } from "node:module";

export const frontend = "http://127.0.0.1:3000";
export const backend = "http://127.0.0.1:19876";
export const workspace = "20000000-0000-4000-8000-000000000001";
export const session = "10000000-0000-4000-8000-000000000003";
const documentUrl = `${frontend}/__loqi_native_discovery_test__`;

export function approvedNativeBackend(url: URL): boolean {
  return url.origin === backend && !url.username && !url.password && (
    ["/__loqi_test/identity", "/api/discoveries", "/api/web/session/_/leads"].includes(url.pathname)
    || /^\/api\/discoveries\/[0-9a-f-]{36}$/.test(url.pathname));
}

type Options = { method?: "GET" | "POST"; body?: unknown;
  approval?: "valid" | "missing" | "invalid"; auth?: "valid" | "missing" | "invalid" };
type Evidence = { method: string; path: string; origin: string | null; requestedHeaders: string | null;
  status: number; allowOrigin: string | null; allowHeaders: string | null; allowMethods: string | null };
type Native = {
  runId: string;
  evidence: Evidence[];
  flush: () => Promise<void>;
  call: (path: string, options?: Options) => Promise<{ status: number; body: any }>;
};

export const test = base.extend<{ native: Native }>({
  native: [async ({ context, page, browserName, baseURL }, use, testInfo) => {
    if (browserName !== "firefox" || baseURL !== frontend
      || process.env.LOQI_RUN_DISCOVERY_HTTP !== "1" || process.env.LOQI_ISOLATED_BACKEND_URL !== backend) {
      throw new Error("Native transport requires Firefox and the exact approved synthetic origins");
    }
    const runId = process.env.LOQI_ISOLATED_BACKEND_RUN_ID || "";
    if (!/^[0-9a-f-]{36}$/.test(runId)) throw new Error("Approve the current synthetic run UUID");
    const blocked: string[] = [];
    const evidence: Evidence[] = [];
    const pending: Promise<void>[] = [];
    let documents = 0;
    // Playwright 1.64's FFNetworkManager drops non-intercepted OPTIONS from
    // public events. Observe the underlying diagnostics without enabling raw
    // debug output or changing Firefox's networking/interception behavior.
    // This version-bound observer fails closed if the diagnostics change.
    const { utils, getPlaywrightVersion } = createRequire(`${process.cwd()}/package.json`)("playwright-core/lib/coreBundle");
    if (getPlaywrightVersion() !== "1.64.0" || typeof utils?.debugLogger?.log !== "function") {
      throw new Error("Review the native preflight observer for this Playwright version");
    }
    const logger = utils.debugLogger;
    const originalLog = logger.log;
    const originalEnabled = logger.isEnabled;
    const preflights = new Map<string, Omit<Evidence, "status" | "allowOrigin" | "allowHeaders" | "allowMethods">>();
    const captureProtocol = (name: string, message: string) => {
      if (name !== "protocol") return originalLog.call(logger, name, message);
      // Never pass protocol messages to a logger/file: they can carry tokens.
      const start = message.indexOf("{");
      if (start < 0) return;
      let packet;
      try { packet = JSON.parse(message.slice(start)); } catch { return; }
      const data = packet.params;
      if (!data) return;
      const key = `${packet.sessionId || ""}:${data.requestId}`;
      const header = (headers: Array<{ name: string; value: string }>, key: string) =>
        headers?.find(row => row.name.toLowerCase() === key)?.value || null;
      if (packet.method === "Network.requestWillBeSent" && data.method === "OPTIONS"
        && approvedNativeBackend(new URL(data.url))) {
        preflights.set(key, { method: "OPTIONS", path: new URL(data.url).pathname,
          origin: header(data.headers, "origin"), requestedHeaders: header(data.headers, "access-control-request-headers") });
      } else if (packet.method === "Network.responseReceived" && preflights.has(key)) {
        evidence.push({ ...preflights.get(key)!, status: data.status,
          allowOrigin: header(data.headers, "access-control-allow-origin"),
          allowHeaders: header(data.headers, "access-control-allow-headers"),
          allowMethods: header(data.headers, "access-control-allow-methods") });
        preflights.delete(key);
      }
    };
    await context.routeWebSocket("**/*", socket => socket.close());
    // This predicate excludes every approved API URL, including browser OPTIONS.
    // Only forbidden requests enter this handler; none are forwarded/continued.
    await context.route(url => url.href !== documentUrl && !approvedNativeBackend(url), async route => {
      const url = new URL(route.request().url());
      blocked.push(`${route.request().method()} ${url.origin}${url.pathname}`);
      await route.abort("blockedbyclient");
    });
    await context.route(documentUrl, async route => {
      if (route.request().method() !== "GET" || !route.request().isNavigationRequest()) {
        blocked.push("Unapproved document request"); await route.abort("blockedbyclient"); return;
      }
      documents++;
      await route.fulfill({ contentType: "text/html", headers: {
        "content-security-policy": `default-src 'none'; connect-src ${backend}; frame-src 'self'; img-src data:`,
      }, body: '<!doctype html><html><head><title>Native synthetic Discovery</title><link rel="icon" href="data:,"></head><body><h1>Native synthetic Discovery</h1></body></html>' });
    });
    context.on("response", response => {
      if (!approvedNativeBackend(new URL(response.url()))) return;
      pending.push((async () => {
        const request = response.request();
        const headers = await response.allHeaders();
        // Capture only transport metadata, never Authorization or run-header values.
        evidence.push({ method: request.method(), path: new URL(response.url()).pathname,
          origin: await request.headerValue("origin"), requestedHeaders: await request.headerValue("access-control-request-headers"),
          status: response.status(), allowOrigin: headers["access-control-allow-origin"] || null,
          allowHeaders: headers["access-control-allow-headers"] || null,
          allowMethods: headers["access-control-allow-methods"] || null });
      })());
    });
    const flush = async () => { await Promise.all(pending); };
    const call: Native["call"] = async (path, options = {}) => {
      const url = new URL(path, backend);
      if (!path.startsWith("/") || path.startsWith("//") || !approvedNativeBackend(url)) {
        throw new Error("Unapproved native API destination");
      }
      return page.evaluate(async ({ url, runId, options, workspace, session, frontend }) => {
        if (location.origin !== frontend) throw new Error("Unapproved document origin");
        const headers: Record<string, string> = {};
        if (!url.endsWith("/__loqi_test/identity")) {
          if (options.auth !== "missing") headers.authorization = options.auth === "invalid" ? "Bearer invalid-synthetic-session" : `Bearer ${session}`;
          if (options.approval !== "missing") headers["x-loqi-test-run-id"] = options.approval === "invalid" ? "unapproved-run" : runId;
          headers["x-workspace-id"] = workspace;
        }
        if (options.body !== undefined) headers["content-type"] = "application/json";
        const response = await fetch(url, { method: options.method || "GET", headers,
          body: options.body === undefined ? undefined : JSON.stringify(options.body),
          mode: "cors", credentials: "omit", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(5000) });
        return { status: response.status, body: await response.json() };
      }, { url: url.href, runId, options, workspace, session, frontend });
    };
    logger.isEnabled = (name: string) => name === "protocol" || originalEnabled.call(logger, name);
    logger.log = captureProtocol;
    try {
      await page.goto(documentUrl);
      expect(await page.locator("script").count()).toBe(0);
      const probe = await call("/__loqi_test/identity");
      if (probe.status !== 200 || probe.body.marker !== "loqi-isolated-discovery-v1" || probe.body.run_id !== runId
        || probe.body.persistence !== "synthetic-memory" || probe.body.outbound_blocked !== true) {
        throw new Error("Native backend identity mismatch");
      }
      await use({ runId, call, evidence, flush });
    } finally {
      logger.log = originalLog;
      logger.isEnabled = originalEnabled;
      await flush();
      console.log("Native Firefox HTTP evidence:", JSON.stringify(evidence));
      await testInfo.attach("native-http-metadata", { body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: "application/json" });
      expect(documents).toBe(1);
      expect(blocked, "No unapproved destination may be attempted").toEqual([]);
      expect(context.serviceWorkers()).toHaveLength(0);
    }
  }, { auto: true }],
});
test.use({ serviceWorkers: "block" });
export { expect };
