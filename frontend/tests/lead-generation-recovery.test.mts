import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { observeLeadGeneration } from "../lib/lead-generation-recovery.ts";
import { ApiError, TimeoutError, generateWorkspaceLeadStrategyDrafts } from "../lib/api.ts";
import type { LeadStrategyGeneration } from "../lib/api.ts";

const state = (status: LeadStrategyGeneration["status"]): LeadStrategyGeneration => ({
  ok: true, job_id: "job", status, stage: status, progress: 0,
  results: status === "completed" ? [{ lead_id: "one", status: "completed", outreach: { subject: "Hi", body: "Hello" } }] : [],
});

test("lost response is reconciled with reads through running to completed", async () => {
  let calls = 0;
  const updates: string[] = [];
  const outcome = await observeLeadGeneration(async () => {
    calls++;
    if (calls === 1) throw new TimeoutError();
    return state(calls === 2 ? "running" : "completed");
  }, (item) => updates.push(item.status), new AbortController().signal, 3, 0);
  assert.equal(outcome, "terminal");
  assert.deepEqual(updates, ["running", "completed"]);
});

test("bounded observer pauses without treating a running job as failed", async () => {
  let calls = 0;
  const outcome = await observeLeadGeneration(async () => { calls++; return state("running"); }, () => {}, new AbortController().signal, 2, 0);
  assert.equal(outcome, "paused"); assert.equal(calls, 2);
});

test("unmount stops observation and ignores stale results without cancelling server work", async () => {
  const controller = new AbortController(); let updates = 0;
  const outcome = await observeLeadGeneration(async () => { controller.abort(); return state("completed"); }, () => updates++, controller.signal, 2, 0);
  assert.equal(outcome, "paused"); assert.equal(updates, 0);
});

test("terminal partial failures keep successful results and authorization errors remain errors", async () => {
  const partial = state("completed"); partial.results.push({ lead_id: "two", status: "failed", error: "Provider unavailable" });
  let received: LeadStrategyGeneration | undefined;
  await observeLeadGeneration(async () => partial, (item) => received = item, new AbortController().signal, 1, 0);
  assert.equal(received?.results.length, 2);
  await assert.rejects(observeLeadGeneration(async () => { throw new ApiError("Workspace denied", 403); }, () => {}, new AbortController().signal, 2, 0), /Workspace denied/);
  await assert.rejects(observeLeadGeneration(async () => { throw new TypeError("bug"); }, () => {}, new AbortController().signal, 2, 0), /bug/);
});

test("explicit generation sends an intent key once; no automatic POST replay", async () => {
  const original = globalThis.fetch; const bodies: string[] = [];
  globalThis.fetch = async (_url, options) => {
    bodies.push(String(options?.body)); return new Response(JSON.stringify(state("queued")), { status: 200 });
  };
  try {
    await generateWorkspaceLeadStrategyDrafts("token", ["one"], "intent");
    assert.equal(bodies.length, 1);
    assert.deepEqual(JSON.parse(bodies[0]), { lead_ids: ["one"], request_key: "intent" });
  } finally { globalThis.fetch = original; }
});

test("page only recovers on mount, keeps analysis on errors, and guards duplicate clicks", async () => {
  const page = await readFile(new URL("../app/(dashboard)/lead-intelligence/page.tsx", import.meta.url), "utf8");
  const effect = page.split("useEffect(() => {")[1].split("}, [urlKey])")[0];
  assert.match(effect, /reconcile\(urlKey\)/);
  assert.doesNotMatch(effect, /generateWorkspaceLeadStrategyDrafts|void generate\(/);
  assert.match(page, /actionPending\.current \|\| generating/);
  assert.match(page, /Check generation status/);
  assert.match(page, /Recover generation request/);
  assert.doesNotMatch(page, /setAnalysis\(null\)/);
});
