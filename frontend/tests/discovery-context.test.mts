import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import {
  DISCOVERY_CONTEXT_KEY, rememberDiscoveryContext, restoredDiscoveryContext,
  rememberedDiscoveryWorkspace, discoveryHistoryUrl, discoverySelectionScope, discoveryResponseIsCurrent,
} from "../lib/discovery-context.ts";
import { generationMatchesSelection } from "../lib/lead-generation-recovery.ts";
import { listWorkspaceLeads, listAuthorizedWorkspaces, selectAuthorizedWorkspace, recoverWorkspaceLeadGeneration } from "../lib/api.ts";

function storage() {
  const rows = new Map<string, string>();
  return { getItem: (key: string) => rows.get(key) || null, setItem: (key: string, value: string) => { rows.set(key, value); } };
}

test("ordinary return restores query, filters, page and durable run without storing results", () => {
  const hint = storage();
  const params = new URLSearchParams("q=SaaS&page=3&industry=software&provider_discovery=run&workspace_id=workspace");
  rememberDiscoveryContext(hint, "user:workspace", params);
  assert.equal(restoredDiscoveryContext(hint, "user:workspace", new URLSearchParams()), `/discovery?${params}`);
  assert.deepEqual(Object.keys(JSON.parse(hint.getItem(DISCOVERY_CONTEXT_KEY)!)).sort(), ["scope", "search"]);
});

test("explicit fresh, historical and campaign URLs win over navigation hints", () => {
  const hint = storage();
  rememberDiscoveryContext(hint, "user:w", new URLSearchParams("q=old&provider_discovery=old-run"));
  for (const search of ["fresh=1", "provider_discovery=history", "q=new", "mode=campaign_attach&campaign_id=c"]) {
    assert.equal(restoredDiscoveryContext(hint, "user:w", new URLSearchParams(search)), null);
  }
});

test("workspace and identity boundaries fail closed, including removed membership and old hints", () => {
  const hint = storage();
  rememberDiscoveryContext(hint, "user:first", new URLSearchParams("q=old"));
  assert.equal(restoredDiscoveryContext(hint, "user:second", new URLSearchParams()), null);
  assert.equal(restoredDiscoveryContext(hint, "other:first", new URLSearchParams()), null);
  assert.equal(rememberedDiscoveryWorkspace(hint, "user", ["first", "second"]), "first");
  assert.equal(rememberedDiscoveryWorkspace(hint, "user", ["second"]), "");
  assert.equal(rememberedDiscoveryWorkspace(hint, "other", ["first"]), "");
  hint.setItem(DISCOVERY_CONTEXT_KEY, "old-unscoped-run-id");
  assert.equal(restoredDiscoveryContext(hint, "user:first", new URLSearchParams()), null);
});

test("history uses the run's own persisted query and supported filters", () => {
  const url = discoveryHistoryUrl({ id: "saved", query: "founders", metadata: { ui_filters: { location: "India", industry: "SaaS", title: "Founder", unsafe: "ignored" } } });
  const params = new URL(url, "https://offline.invalid").searchParams;
  assert.equal(params.get("q"), "founders"); assert.equal(params.get("provider_discovery"), "saved");
  assert.equal(params.get("location"), "India"); assert.equal(params.get("title"), "Founder");
  assert.equal(params.get("unsafe"), null);
});

test("pagination preserves selection identity; filters, query, run, campaign and workspace invalidate it", () => {
  const params = new URLSearchParams("q=founders&page=1&provider_discovery=run");
  const scope = discoverySelectionScope("user:w", params);
  params.set("page", "2"); assert.equal(discoverySelectionScope("user:w", params), scope);
  for (const key of ["q", "location", "industry", "company", "title", "keywords", "provider_discovery", "campaign_id"]) {
    const changed = new URLSearchParams(params); changed.set(key, "different");
    assert.notEqual(discoverySelectionScope("user:w", changed), scope);
  }
  assert.notEqual(discoverySelectionScope("user:other", params), scope);
});

test("late responses cannot overwrite new query, restoration, workspace or a newer retry of the same page", async () => {
  let complete!: () => void;
  const deferred = new Promise<void>((resolve) => { complete = resolve; });
  const captured = { scope: "user:w:query-A:page1", revision: 1 };
  let current = { ...captured };
  let updates = 0;
  const controller = new AbortController();
  const old = deferred.then(() => { if (discoveryResponseIsCurrent(captured, current, true, controller.signal)) updates++; });
  current = { scope: "user:w:query-B:page1", revision: 2 };
  complete(); await old;
  assert.equal(updates, 0); // The simulated transport ignores cancellation.
  assert.equal(discoveryResponseIsCurrent(captured, { ...captured, revision: 3 }, true, controller.signal), false);
  assert.equal(discoveryResponseIsCurrent(captured, { scope: "other-workspace", revision: 1 }, true, controller.signal), false);
  assert.equal(discoveryResponseIsCurrent(captured, captured, false, controller.signal), false);
  assert.equal(discoveryResponseIsCurrent(captured, captured, true, controller.signal), true);
  controller.abort(); assert.equal(discoveryResponseIsCurrent(captured, captured, true, controller.signal), false);
});

test("generation recovery cannot display a job belonging to previous selected IDs", () => {
  const state = { ok: true, lead_ids: ["a", "b"], job_id: "job", status: "queued" as const, stage: "Queued", progress: 0, results: [] };
  assert.equal(generationMatchesSelection(state, ["b", "a"]), true);
  assert.equal(generationMatchesSelection(state, ["c"]), false);
  assert.equal(generationMatchesSelection({ ...state, lead_ids: undefined }, ["a", "b"]), false);
});

test("scope headers reach existing APIs and result reconciliation remains read-only", async () => {
  const original = globalThis.fetch;
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return new Response(JSON.stringify({ ok: true, leads: [], total: 0, workspaces: [{ id: "w" }], lead_ids: ["a"] }), { status: 200 });
  };
  try {
    await listAuthorizedWorkspaces();
    await listWorkspaceLeads("offline", "founders", 2, { location: "US" }, "run", new AbortController().signal, "w");
    await recoverWorkspaceLeadGeneration("intent", undefined, "w");
    assert.equal(new Headers(calls[1].options?.headers).get("X-Workspace-Id"), "w");
    assert.equal(new Headers(calls[2].options?.headers).get("X-Workspace-Id"), "w");
    assert.ok(calls.every((call) => !call.options?.method || call.options.method === "GET"));
    assert.match(calls[1].url, /discovery_id=run/);
  } finally { globalThis.fetch = original; }
});

test("workspace selection validates through the existing endpoint and carries requested scope", async () => {
  const original = globalThis.fetch;
  let call: { url: string; options?: RequestInit } | undefined;
  globalThis.fetch = async (url, options) => {
    call = { url: String(url), options };
    return new Response(JSON.stringify({ ok: true, workspace: { id: "workspace-b", name: "Beta" } }), { status: 200 });
  };
  try {
    const result = await selectAuthorizedWorkspace("workspace-b");
    assert.equal(result.workspace.name, "Beta");
    assert.match(call!.url, /\/api\/web\/session\/_\/workspaces\/select$/);
    assert.equal(call!.options?.method, "POST");
    assert.equal(new Headers(call!.options?.headers).get("X-Workspace-Id"), "workspace-b");
  } finally { globalThis.fetch = original; }
});

test("page owners guard restoration, polling, handoff and unmount without submitting or cancelling jobs", async () => {
  const page = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
  const intelligence = await readFile(new URL("../app/(dashboard)/lead-intelligence/page.tsx", import.meta.url), "utf8");
  const restore = page.slice(page.indexOf("const restoreDurableRun"), page.indexOf("const loadWorkspaceLeads"));
  assert.doesNotMatch(restore, /startDiscoverySearch|runSearch\(/);
  assert.match(restore, /revision !== intent.current/);
  assert.match(page, /currentRunId.current !== providerDiscoveryId/);
  assert.match(page, /void resultLoader.current\(\)/);
  assert.match(page, /This saved search is unavailable/);
  assert.match(page, /key=\{selectionScope\}/);
  assert.match(page, /getNavState<string\[\]>\(`discovery:\$\{scope\}`, selectionScope\)/);
  assert.match(page, /if \(selectedScope === selectionScope\) setNavState/);
  assert.match(page, /leadIds=\{\[\.\.\.currentSelection\]\}/);
  assert.match(page, /workspace_id=\$\{encodeURIComponent\(workspaceId\)\}&lead_ids=/);
  assert.match(page, /loadedScope !== currentResultScope.current/);
  assert.doesNotMatch(page, /cancelDiscovery|stopDiscovery/);
  assert.match(intelligence, /key=\{`\$\{context.scope\}:\$\{ids.join/);
  assert.match(intelligence, /if \(!mounted.current \|\| controller.signal.aborted\) return/);
  assert.match(intelligence, /generationKey !== requestKey.current/);
  assert.match(intelligence, /generationMatchesSelection\(state, ids\)/);
  const recovery = intelligence.slice(intelligence.indexOf("useEffect(() => {"), intelligence.indexOf("const analyze ="));
  assert.doesNotMatch(recovery, /generateWorkspaceLeadStrategyDrafts|analyzeWorkspaceLeads/);
});
