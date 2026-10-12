import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { getCampaign, listDrafts, updateDraft, listCampaignDrafts, listCampaigns, approveDraft, generateCampaignStrategy, getStrategyGenerationStatus, generateCampaignDrafts, getCampaignGenerationStatus, refineDraft } from "../lib/api.ts";
import { scopedKey, swrFetch, peekCache, clearClientCache } from "../lib/client-cache.ts";
import { discoveryReturnUrl } from "../lib/discovery-context.ts";

test("campaign, drafts, edits and explicit job requests send the same workspace header", async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_input, options) => {
    calls++;
    assert.equal(new Headers(options?.headers).get("X-Workspace-Id"), "ws-b");
    return new Response(JSON.stringify({ ok: true, drafts: [], campaigns: [], campaign: {}, draft: {}, status: "completed" }), { status: 200 });
  };
  try {
    await getCampaign("offline", "campaign", "ws-b");
    await listCampaignDrafts("offline", "campaign", "ws-b");
    await listDrafts("offline", "ws-b");
    await listCampaigns("offline", "ws-b");
    await updateDraft("offline", "draft", "Subject: \n\nMessage", "ws-b");
    await approveDraft("offline", "draft", "ws-b");
    await refineDraft("offline", "draft", "Shorter", "Message", {}, undefined, "ws-b");
    await generateCampaignStrategy("offline", "campaign", false, "ws-b");
    await getStrategyGenerationStatus("offline", "campaign", "job", "ws-b");
    await generateCampaignDrafts("offline", "campaign", "ws-b");
    await getCampaignGenerationStatus("offline", "campaign", "ws-b");
    assert.equal(calls, 11);
  } finally { globalThis.fetch = previous; }
});

test("late responses remain in the original workspace cache", async () => {
  clearClientCache();
  for (const resource of ["campaign", "drafts", "campaigns-meta"]) {
    const a = scopedKey("session", resource, "ws-a", "entity");
    const b = scopedKey("session", resource, "ws-b", "entity");
    assert.notEqual(a, b);
    let release!: (value: string) => void;
    const old = swrFetch(a, () => new Promise<string>(resolve => { release = resolve; }));
    assert.equal(await swrFetch(b, async () => "Workspace B"), "Workspace B");
    release("Late workspace A"); await old;
    assert.equal(peekCache<string>(b)?.value, "Workspace B");
  }
  clearClientCache();
});

test("return navigation reuses the working URL only in its workspace/identity", () => {
  const storage = { getItem: () => JSON.stringify({ scope: "actor:ws-b", search: "q=founders&workspace_id=ws-b&provider_discovery=run&page=2" }) };
  assert.equal(discoveryReturnUrl(storage, "actor:ws-b", "ws-b"), "/discovery?q=founders&workspace_id=ws-b&provider_discovery=run&page=2");
  assert.equal(discoveryReturnUrl(storage, "actor:ws-a", "ws-a"), "/discovery?workspace_id=ws-a");
  const stale = { getItem: () => JSON.stringify({ scope: "actor:ws-b", search: "q=old&workspace_id=ws-a" }) };
  assert.equal(discoveryReturnUrl(stale, "actor:ws-b", "ws-b"), "/discovery?workspace_id=ws-b");
});

test("page owners remount per scope/entity and do not render unresolved scope", async () => {
  const campaign = await readFile(new URL("../app/(dashboard)/campaigns/[id]/page.tsx", import.meta.url), "utf8");
  const draft = await readFile(new URL("../components/draft/DraftReviewWorkspace.tsx", import.meta.url), "utf8");
  const inline = await readFile(new URL("../components/campaigns/CampaignDraftsSection.tsx", import.meta.url), "utf8");
  const action = await readFile(new URL("../components/dashboard/DiscoveryCampaignActions.tsx", import.meta.url), "utf8");
  const repository = await readFile(new URL("../lib/repositories.ts", import.meta.url), "utf8");
  for (const page of [campaign, draft]) {
    assert.match(page, /useIntelligenceWorkspace/);
    assert.match(page, /if \(!context.workspace\) return/);
    assert.match(page, /context.scope/);
    assert.match(page, /mounted.current/);
  }
  assert.ok(campaign.includes('key={`${context.scope}:${campaignId}`}'));
  assert.ok(draft.includes('key={`${context.scope}:${campaignId}`}'));
  assert.match(campaign, /scopedKey\(sessionToken, "campaign", workspaceId, campaignId\)/);
  assert.match(draft, /scopedKey\(sessionToken, "drafts", workspaceId\)/);
  assert.match(draft, /draft-review:\$\{sessionToken\}:\$\{workspaceId\}/);
  assert.match(repository, /getCampaign\(token, id, workspaceId\)/);
  assert.match(action, /campaigns\/\$\{completedId\}\?workspace_id=/);
  assert.match(inline, /campaign=\$\{encodeURIComponent\(campaignId\)\}&workspace_id=/);
  assert.match(draft, /updateDraft\(sessionToken, selected.id, full, workspaceId\)/);
  assert.match(draft, /Draft context unavailable/);
});
