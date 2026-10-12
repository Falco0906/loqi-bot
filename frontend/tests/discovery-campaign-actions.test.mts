import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { campaignContainsLeadIds } from "../lib/campaign-attachment-reconciliation.ts";
import { addLeadToCampaign, getCampaign, saveCampaign } from "../lib/api.ts";

const page = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
const actions = await readFile(new URL("../components/dashboard/DiscoveryCampaignActions.tsx", import.meta.url), "utf8");
const detail = await readFile(new URL("../app/(dashboard)/discovery/[id]/page.tsx", import.meta.url), "utf8");

test("unified Discovery exposes campaign actions and optional intelligence independently", () => {
  assert.match(page, /DiscoveryCampaignActions/);
  assert.match(page, /Analyze with Loqi/);
  assert.match(actions, /Add to existing campaign/);
  assert.match(actions, /Create campaign with selected leads/);
  assert.doesNotMatch(actions, /decideLead|generateStrategy|lead-intelligence|startDiscoverySearch/);
});

test("existing campaign contracts receive only canonical selected IDs", () => {
  assert.match(actions, /addLeadToCampaign\(token\(\), destination, \{ id, workspace_lead_id: id \}/);
  assert.match(actions, /saveCampaign\(token\(\), intent.name/);
  assert.match(actions, /intent.ids.map\(\(id\) => \(\{ id, workspace_lead_id: id \}\)\)/);
  assert.match(actions, /if \(busyRef.current \|\| !leadIds.length/);
  assert.match(actions, /Promise.allSettled/);
});

test("campaign route mounts unified workspace without starting a search", () => {
  const entry = page.slice(page.indexOf("export default function DiscoveryPage"));
  assert.match(entry, /return <DiscoveryWorkspace key=\{context.scope\}/);
  assert.doesNotMatch(page, /DiscoveryHistory/);
  assert.doesNotMatch(entry, /startDiscoverySearch|runSearch/);
  assert.match(page, /url.set\("mode", "campaign_attach"\)/);
  assert.match(page, /url.set\("campaign_id", campaignContext\)/);
  assert.match(actions, /getCampaign\(token\(\), campaignContext, workspaceId\)/);
  assert.match(actions, /unavailable in the selected workspace/);
  assert.match(actions, /Leave campaign context/);
  assert.match(detail, /mode.mode === "campaign_attach"/);
  assert.match(detail, /return <CampaignDiscoveryRedirect/);
  assert.match(detail, /provider_discovery=\$\{encodeURIComponent\(run.id\)\}/);
  assert.doesNotMatch(detail, /startDiscoverySearch|startCampaignResearch/);
});

test("search changes clear selection, pagination does not, and stale hydration cannot replace current results", () => {
  assert.match(page, /selectionScope = discoverySelectionScope\(scope/);
  assert.match(page, /if \(selectionOwner.current !== selectionScope\)/);
  assert.match(page, /setSelected\(new Set\(\)\);\s*setSelectedScope\(selectionScope\)/);
  assert.match(page, /discoveryResponseIsCurrent/);
  assert.match(page, /campaignBusyRef.current \|\| loading/);
});

test("lost attachment responses reconcile read-only, never automatically repeat a mutation", () => {
  assert.equal(campaignContainsLeadIds({ leads: [{ id: "a" }, { id: "b" }] }, ["a", "b"]), true);
  assert.equal(campaignContainsLeadIds({ leads: [{ id: "a" }] }, ["a", "b"]), false);
  assert.match(actions, /Check attachment status/);
  assert.match(actions, /checkAttachment\(uncertain.campaignId, uncertain.leadIds\)/);
  assert.match(actions, /Campaign creation outcome is unknown/);
  assert.equal((actions.match(/addLeadToCampaign\(token/g) || []).length, 1);
  assert.equal((actions.match(/saveCampaign\(token/g) || []).length, 1);
});

test("explicit discovery remains manual and beta capabilities remain authoritative", () => {
  assert.match(page, /useBetaFeature\("lead_search"\)/);
  assert.match(page, /startDiscoverySearch\(nextQuery, "manual", workspaceId, filters\)/);
  assert.doesNotMatch(actions, /launchCampaign|sendDraft|scheduleDraft|autonomous_lead_sourcing/);
});

test("attachment and creation send canonical references through the existing endpoints without analysis", async () => {
  const originalFetch = globalThis.fetch;
  const originalStorage = globalThis.localStorage;
  const requests: Array<{ url: string; options?: RequestInit }> = [];
  globalThis.localStorage = { getItem: () => "test-token" } as Storage;
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return new Response(JSON.stringify({ ok: true, added: true, campaign: { id: "campaign", leads: [{ id: "saved-id" }] } }), { status: 200 });
  };
  try {
    const reference = { id: "saved-id", workspace_lead_id: "saved-id" };
    assert.equal((await addLeadToCampaign("test-token", "campaign", reference)).added, true);
    assert.equal((await saveCampaign("test-token", "Selected", undefined, undefined, 1, undefined, "planning", [reference], undefined, "selected-intent")).ok, true);
    await getCampaign("test-token", "campaign");
    assert.match(requests[0].url, /\/campaigns\/campaign\/leads$/);
    assert.deepEqual(JSON.parse(String(requests[0].options?.body)), { lead: reference });
    assert.match(requests[1].url, /\/campaigns$/);
    assert.deepEqual(JSON.parse(String(requests[1].options?.body)).leads, [reference]);
    assert.equal(requests[2].options?.method, "GET");
    assert.equal(requests.filter((request) => request.options?.method === "POST").length, 2);
    assert.ok(requests.every((request) => !request.url.includes("intelligence") && !request.url.includes("send")));
  } finally { globalThis.fetch = originalFetch; globalThis.localStorage = originalStorage; }
});

test("attachment failures are not automatically retried by the API client", async () => {
  const originalFetch = globalThis.fetch;
  const originalStorage = globalThis.localStorage;
  let calls = 0;
  globalThis.localStorage = { getItem: () => "test-token" } as Storage;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(JSON.stringify({ detail: "Persistence unavailable" }), { status: 503 });
  };
  try {
    await assert.rejects(addLeadToCampaign("test-token", "campaign", { id: "saved-id", workspace_lead_id: "saved-id" }));
    assert.equal(calls, 1);
  } finally { globalThis.fetch = originalFetch; globalThis.localStorage = originalStorage; }
});
