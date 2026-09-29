import assert from "node:assert";
import { test } from "node:test";

let capturedBody: Record<string, unknown> | null = null;

(globalThis as typeof globalThis & { fetch: typeof fetch }).fetch = async (_url, options) => {
  capturedBody = JSON.parse(String(options?.body || "{}")) as Record<string, unknown>;
  return new Response(
    JSON.stringify({ ok: true, job_id: "job-1", discovery_id: "discovery-1", status: "queued" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
};

const { startDiscoveryJob } = await import("../lib/api.ts");

test("explicit provider Discovery search sends manual initiation", async () => {
  await startDiscoveryJob("session-token", "SaaS operations leaders", "manual");
  assert.deepEqual(capturedBody, {
    query: "SaaS operations leaders",
    initiation: "manual",
  });
});

test("legacy callers remain automated unless they explicitly opt in", async () => {
  await startDiscoveryJob("session-token", "SaaS operations leaders");
  assert.equal(capturedBody?.initiation, "automated");
});
