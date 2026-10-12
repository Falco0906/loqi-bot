import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { saveCampaign } from "../lib/api.ts";

test("missing, blank and oversized keys are rejected before any request", async () => {
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; throw new Error("No request is permitted"); };
  try {
    for (const key of [undefined, "", "   ", "x".repeat(129)]) {
      await assert.rejects(saveCampaign("token", "Campaign", undefined, undefined, undefined, undefined, undefined, undefined, undefined, key), /stable idempotency key/);
    }
    assert.equal(requests, 0);
  } finally { globalThis.fetch = originalFetch; }
});

test("explicit retry carries the same intent key through the existing creation API", async () => {
  const originalFetch = globalThis.fetch;
  const originalStorage = globalThis.localStorage;
  const bodies: Array<Record<string, unknown>> = [];
  globalThis.localStorage = { getItem: () => "test-token" } as Storage;
  globalThis.fetch = async (_url, options) => {
    bodies.push(JSON.parse(String(options?.body)));
    return new Response(JSON.stringify({ ok: true, campaign: { id: "same-campaign" } }), { status: 200 });
  };
  try {
    const create = () => saveCampaign("token", "Selected", "Meet buyers", undefined, 1, undefined, "planning", [{ workspace_lead_id: "saved" }], undefined, "stable-intent-key");
    assert.deepEqual(await create(), await create());
    assert.deepEqual(bodies[0], bodies[1]);
    assert.equal(bodies[0].idempotency_key, "stable-intent-key");
    await saveCampaign("token", "Selected", "Meet buyers", undefined, 1, undefined, "planning", [{ workspace_lead_id: "saved" }], undefined, "unrelated-intent-key");
    assert.notEqual(bodies[2].idempotency_key, bodies[0].idempotency_key);
  } finally { globalThis.fetch = originalFetch; globalThis.localStorage = originalStorage; }
});

test("creation owners retain keys across lost responses; recovery is explicit", async () => {
  const page = await readFile(new URL("../app/(dashboard)/campaigns/new/page.tsx", import.meta.url), "utf8");
  const actions = await readFile(new URL("../components/dashboard/DiscoveryCampaignActions.tsx", import.meta.url), "utf8");
  assert.match(page, /useRef\(searchParams\?\.get\("creation_key"\)/);
  assert.match(page, /creationKey.current,/);
  assert.match(page, /if \(savingRef.current\) return/);
  assert.match(actions, /campaign_creation_key/);
  assert.match(actions, /undefined, intent.key, workspaceId\)/);
  assert.match(actions, /Recover campaign creation/);
  assert.match(actions, /await createSelectedCampaign\(creationIntent.current\)/);
});

test("campaign page no longer waits for implicit strategy generation, explicit actions remain", async () => {
  const page = await readFile(new URL("../app/(dashboard)/campaigns/[id]/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /waitingForCarriedStrategy|carried-strategy poll/);
  assert.match(page, /generateCampaignStrategy\(token, campaignId, force, workspaceId\)/);
  assert.match(page, /onGenerateStrategy=\{\(\) => void generateStrategy\(\)\}/);
});
