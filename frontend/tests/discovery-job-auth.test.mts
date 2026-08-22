/**
 * PR-4 HOTFIX — Discovery job-status requests must be authenticated.
 *
 * Production incident: GET /api/jobs/{job_id} returned 401 because
 * getJob/getJobResults sent no Authorization header. Creation succeeded
 * (startSearchJob sends the web-session Bearer) but every subsequent poll was
 * unauthenticated → infinite 401 poll loop, discovery stuck on WORKING.
 *
 * This test drives the REAL lib/api functions through a stubbed global fetch
 * and asserts the Authorization header is present and carries the active
 * web-session token.
 *
 * Run: node tests/discovery-job-auth.test.mts (Node 22.6+ type-stripping)
 */

import assert from "node:assert";
import { test } from "node:test";

const SESSION_TOKEN = "web-session-token-abc";

const storage = new Map<string, string>([["loqi_active_session_token", SESSION_TOKEN]]);
(globalThis as any).localStorage = {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => { storage.set(k, v); },
  removeItem: (k: string) => { storage.delete(k); },
};

let captured: { url: string; options: RequestInit } | null = null;
(globalThis as any).fetch = async (url: any, options: any = {}) => {
  captured = { url: String(url), options };
  return new Response(
    JSON.stringify({ id: jobId(), status: "running" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
};

let _id = "job-123";
function jobId(): string { return _id; }

const { getJob, getJobResults } = await import("../lib/api.ts");

function authHeader(): string | undefined {
  const headers = (captured?.options?.headers ?? {}) as Record<string, string>;
  return headers.Authorization;
}

test("getJob sends the active web-session token as Bearer", async () => {
  captured = null;
  await getJob("job-123");
  assert.ok(captured!.url.includes("/api/jobs/job-123"), `url: ${captured!.url}`);
  assert.equal(authHeader(), `Bearer ${SESSION_TOKEN}`);
});

test("getJobResults sends the same credential", async () => {
  captured = null;
  await getJobResults("job-123");
  assert.ok(captured!.url.includes("/api/jobs/job-123/results"));
  assert.equal(authHeader(), `Bearer ${SESSION_TOKEN}`);
});

test("explicit sessionToken argument overrides localStorage", async () => {
  captured = null;
  await getJob("job-123", "explicit-token");
  assert.equal(authHeader(), "Bearer explicit-token");
});

test("no stored token → request still goes out without a fabricated header", async () => {
  storage.delete("loqi_active_session_token");
  captured = null;
  await getJob("job-123");
  assert.ok(captured!.url.includes("/api/jobs/job-123"));
  assert.equal(authHeader(), undefined);
  // restore for other tests
  storage.set("loqi_active_session_token", SESSION_TOKEN);
});
