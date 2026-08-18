/**
 * Regression: the strategic-intelligence API client must authenticate with the
 * canonical access token.
 *
 * Production incident: after a successful email signup → verification →
 * completion → onboarding conversation, POST /api/v1/strategic-intelligence/
 * generate returned 401 "Authentication required" because this client sent no
 * Authorization header (the backend route requires `get_current_auth`).
 *
 * This guards the frontend/API boundary: the request MUST carry
 * `Authorization: Bearer <loqi_access_token>`.
 *
 * Run with: node tests/strategic-intelligence-auth.test.mts
 * (Node 22.6+ native TS type-stripping)
 */

import assert from "node:assert";
import {
  generateStrategicProfile,
  getStrategicProfile,
} from "../lib/strategic-intelligence-api.ts";

const FAKE_TOKEN = "test-access-token-123";

const storage = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => { storage.set(k, v); },
  removeItem: (k: string) => { storage.delete(k); },
};

let captured: { url: string; options: RequestInit } | null = null;
(globalThis as any).fetch = async (url: any, options: any = {}) => {
  captured = { url: String(url), options };
  return new Response(
    JSON.stringify({ profile: { COMPANY_SUMMARY: "X" }, generated_at: "now" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
};

function capturedAuth(): string | undefined {
  const headers = (captured?.options?.headers ?? {}) as Record<string, string>;
  return headers.Authorization;
}

async function main(): Promise<void> {
  // Without a stored token, the client still must not crash and must not send
  // a stray Authorization header.
  storage.delete("loqi_access_token");
  captured = null;
  await getStrategicProfile("some-user");
  assert.ok(captured, "getStrategicProfile must perform a request");
  assert.strictEqual(capturedAuth(), undefined, "no token → no Authorization header");

  // With a stored access token, both calls must attach it.
  storage.set("loqi_access_token", FAKE_TOKEN);

  captured = null;
  await generateStrategicProfile({
    company_description: "d",
    ideal_customer: "i",
    differentiation: "x",
    annual_goal: "g",
    biggest_obstacle: "o",
  });
  assert.ok(captured, "generateStrategicProfile must perform a request");
  assert.ok(
    captured.url.includes("/api/v1/strategic-intelligence/generate"),
    `unexpected url: ${captured.url}`,
  );
  assert.strictEqual(
    capturedAuth(),
    `Bearer ${FAKE_TOKEN}`,
    "generate must send Authorization: Bearer <loqi_access_token>",
  );

  captured = null;
  await getStrategicProfile("some-user");
  assert.ok(captured, "getStrategicProfile must perform a request");
  assert.strictEqual(
    capturedAuth(),
    `Bearer ${FAKE_TOKEN}`,
    "profile fetch must send Authorization: Bearer <loqi_access_token>",
  );

  console.log("strategic-intelligence-auth: PASS");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
