/** Real HTTP Discovery backend; canned replies are restricted to unrelated shell UI. */
import { test as base, expect } from "@playwright/test";
import { request as httpRequest } from "node:http";
import { MockApi, ids } from "./fixtures";

export const session = "10000000-0000-4000-8000-000000000003";
const backend = "http://127.0.0.1:19876";
const marker = "loqi-isolated-discovery-v1";

function approved(method: string, path: string) {
  return (method === "GET" && ["/health", "/__loqi_test/identity", "/api/v1/auth/me", "/api/v1/beta/features",
    "/api/web/session/_/workspaces", "/api/web/session/_/leads", "/api/discoveries"].includes(path))
    || (method === "GET" && /^\/api\/discoveries\/[0-9a-f-]{36}$/.test(path))
    || (method === "POST" && ["/api/discoveries", "/api/v1/auth/refresh", "/__loqi_test/fault"].includes(path));
}

export async function backendRequest(method: string, path: string, body?: string, headers: Record<string, string> = {}) {
  if (process.env.LOQI_RUN_DISCOVERY_HTTP !== "1" || process.env.LOQI_ISOLATED_BACKEND_URL !== backend
      || !/^[0-9a-f-]{36}$/.test(process.env.LOQI_ISOLATED_BACKEND_RUN_ID || "")
      || (headers.authorization && headers.authorization !== `Bearer ${session}`)
      || !path.startsWith("/") || path.startsWith("//")
      || !approved(method, new URL(path, backend).pathname)) throw new Error("Unapproved isolated request");
  // Fixed numeric loopback destination; no URL/redirect/proxy/credential fallback.
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const request = httpRequest({ hostname: "127.0.0.1", port: 19876, path, method, agent: false,
      headers: { ...headers, "x-loqi-test-run-id": process.env.LOQI_ISOLATED_BACKEND_RUN_ID || "" }, timeout: 5000 }, response => {
      let text = "";
      response.setEncoding("utf8");
      response.on("data", chunk => { text += chunk; if (text.length > 2_000_000) request.destroy(new Error("Oversized fixture response")); });
      response.on("end", () => resolve({ status: response.statusCode || 0, body: text }));
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error("Isolated backend unavailable")));
    request.on("error", reject);
    request.end(body);
  });
}

export type IsolatedCall = { method: string; path: string; workspace: string; url: URL };
type IsolatedReply = { status: number; body: string };
type Transport = {
  calls: IsolatedCall[];
  delivered: IsolatedCall[];
  before?: (call: IsolatedCall) => Promise<IsolatedReply | undefined>;
  after?: (call: IsolatedCall, reply: IsolatedReply) => Promise<void>;
};

export const test = base.extend<{ isolated: { runId: string }; transport: Transport }>({
  transport: async ({}, use) => { await use({ calls: [], delivered: [] }); },
  isolated: [async ({ context, baseURL, transport }, use) => {
    if (process.env.LOQI_RUN_DISCOVERY_HTTP !== "1" || !baseURL
      || !/^http:\/\/(?:127\.0\.0\.1|localhost):3000\/?$/.test(baseURL)) throw new Error("Explicit isolated HTTP test opt-in and loopback frontend are required");
    const expected = process.env.LOQI_ISOLATED_BACKEND_RUN_ID;
    if (!expected || !/^[0-9a-f-]{36}$/.test(expected)) throw new Error("Approve the isolated backend run ID printed at startup");
    const probe = await backendRequest("GET", "/__loqi_test/identity");
    const identity = JSON.parse(probe.body);
    if (probe.status !== 200 || identity.marker !== marker || identity.run_id !== expected
      || identity.persistence !== "synthetic-memory" || identity.outbound_blocked !== true) throw new Error("Isolated backend identity mismatch");
    const shell = new MockApi();
    const blocked: string[] = [];
    const frontend = new URL(baseURL).origin;
    await context.routeWebSocket("**/*", socket => socket.close());
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === frontend && url.pathname === "/__nextjs_original-stack-frames" && request.method() === "POST") {
        // Expected HTTP errors invoke Next's local development error overlay.
        // Its supported 204 fallback retains the error without fetching source
        // mappings. Never forward diagnostics to any server or log their body.
        await route.fulfill({ status: 204, body: "" }); return;
      }
      if (["fonts.googleapis.com", "fonts.gstatic.com"].includes(url.hostname)) {
        await route.fulfill({ body: "", contentType: "text/css" }); return;
      }
      if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
        if (![frontend, backend, "http://127.0.0.1:10000", "http://localhost:10000"].includes(url.origin)) {
          blocked.push("Unapproved API origin"); await route.abort("blockedbyclient"); return;
        }
        if (request.method() === "OPTIONS") {
          await route.fulfill({ status: 204, headers: { "access-control-allow-origin": frontend,
            "access-control-allow-methods": "GET, POST", "access-control-allow-headers": "authorization,content-type,x-workspace-id" } }); return;
        }
        if (approved(request.method(), url.pathname)) {
          const headers: Record<string, string> = {};
          for (const name of ["authorization", "content-type", "x-workspace-id"]) {
            const value = request.headers()[name];
            if (value) headers[name] = value;
          }
          if (headers.authorization && headers.authorization !== `Bearer ${session}`) throw new Error("Only synthetic credentials may be forwarded");
          // Faults/delays run only AFTER the existing origin, route and credential
          // checks. They cannot select a destination or intercept the run probe.
          const call = { method: request.method(), path: url.pathname, workspace: headers["x-workspace-id"] || "", url };
          transport.calls.push(call);
          const response = await transport.before?.(call)
            ?? await backendRequest(request.method(), url.pathname + url.search, request.postData() || undefined, headers);
          await transport.after?.(call, response);
          await route.fulfill({ status: response.status, body: response.body, contentType: "application/json", headers: { "access-control-allow-origin": frontend } });
          transport.delivered.push(call);
          return;
        }
        // Only existing, declared shell mocks may answer ancillary requests.
        // Discovery/leads/workspaces cannot fall back to MockApi's canned data.
        if (!/\/api\/(?:discoveries|jobs)|\/leads|\/workspaces/.test(url.pathname)) {
          const reply = await shell.reply({ method: request.method(), path: url.pathname, url,
            workspace: request.headers()["x-workspace-id"] || "", body: request.postData() ? JSON.parse(request.postData()!) : {} });
          if (reply) { await route.fulfill({ status: reply.status || 200, json: reply.json }); return; }
        }
      } else if (url.origin === frontend && request.method() === "GET") {
        await route.continue(); return;
      }
      blocked.push(`${request.method()} ${url.pathname}`);
      await route.abort("blockedbyclient");
    });
    await context.addInitScript(({ user, org, session }) => {
      localStorage.setItem("loqi_user_id", user); localStorage.setItem("loqi_org_id", org);
      for (const key of ["loqi_access_token", "loqi_refresh_token", "loqi_active_session_token"]) localStorage.setItem(key, session);
    }, { user: ids.user, org: ids.org, session });
    try { await use({ runId: expected }); }
    finally { expect(blocked, "Unapproved requests must never escape").toEqual([]); }
  }, { auto: true }],
});
export { expect, ids };
