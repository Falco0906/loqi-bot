import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { ApiError, saveCampaign } from "../lib/api.ts";

// Execute the actual adapter with a tiny hook scheduler and an injected API.
// These are offline logic regressions, not mounted browser/React verification.
async function workspaceHarness() {
  const source = await readFile(new URL("../hooks/useCampaignWorkspace.ts", import.meta.url), "utf8");
  const slots: any[] = [];
  let cursor = 0;
  let user: any = { id: "actor", organization: { id: "org" } };
  let isLoading = false;
  const effects: Array<() => void> = [];
  const calls: Array<{ signal: AbortSignal; resolve: (value: any) => void; reject: (error: Error) => void }> = [];
  const react = {
    useState(initial: any) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], (value: any) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial: any) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(fn: any) { return fn; },
    useEffect(fn: any, dependencies: any[]) {
      const index = cursor++;
      const prior = slots[index];
      if (!prior || dependencies.some((value, i) => value !== prior.dependencies[i])) {
        effects.push(() => { prior?.cleanup?.(); slots[index] = { dependencies, cleanup: fn() }; });
      }
    },
  };
  const exports: any = {};
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, AbortController,
    require(name: string) {
      if (name === "react") return react;
      if (name === "./useAuth") return { useAuth: () => ({ user, isLoading }) };
      if (name === "../lib/api") return { listAuthorizedWorkspaces: (signal: AbortSignal) => new Promise((resolve, reject) => calls.push({ signal, resolve, reject })) };
      throw new Error(`Unexpected campaign adapter dependency: ${name}`);
    },
  });
  return {
    calls,
    setUser(value: any) { user = value; },
    setAuthLoading(value: boolean) { isLoading = value; },
    render(requested = "") {
      cursor = 0;
      const result = exports.useCampaignWorkspace(requested);
      while (effects.length) effects.shift()!();
      return result;
    },
    async complete(index: number, ids: string[]) {
      calls[index].resolve({ ok: true, workspaces: ids.map((id) => ({ id, name: id })) });
      await Promise.resolve();
      await Promise.resolve();
    },
  };
}

test("campaign workspace accepts only an authorized explicit scope or a single membership", async () => {
  const h = await workspaceHarness();
  assert.equal(h.render("selected").loading, true);
  await h.complete(0, ["default", "selected"]);
  assert.equal(h.render("selected").workspace, "selected");
  assert.equal(h.render("selected").scope, "actor:selected");
  assert.equal(h.render("invalid").workspace, "");
  await h.complete(1, ["default", "selected"]);
  assert.match(h.render("invalid").error, /unavailable or inaccessible/);
  h.render();
  await h.complete(2, ["default", "selected"]);
  assert.match(h.render().error, /explicitly/);
  h.render().retry();
  h.render();
  await h.complete(3, ["single"]);
  assert.equal(h.render().workspace, "single");
});

test("empty membership, listing failure and missing authentication are recoverable", async () => {
  const h = await workspaceHarness();
  h.setAuthLoading(true);
  assert.equal(h.render().loading, true);
  assert.equal(h.render().error, "");
  assert.equal(h.calls.length, 0);
  h.setAuthLoading(false);
  h.render();
  await h.complete(0, []);
  assert.match(h.render().error, /No accessible workspace/);
  h.render().retry();
  assert.equal(h.render().loading, true);
  h.calls[1].reject(new Error("offline unavailable"));
  await Promise.resolve(); await Promise.resolve();
  assert.match(h.render().error, /could not be loaded/);
  h.render().retry(); h.render();
  await h.complete(2, ["single"]);
  assert.equal(h.render().workspace, "single");
  h.setUser(null);
  assert.equal(h.render().workspace, "");
  assert.match(h.render().error, /Sign in/);
  assert.equal(h.calls.length, 3);
});

test("obsolete identity and workspace responses cannot restore the previous scope even when abort is ignored", async () => {
  const h = await workspaceHarness();
  h.render("old");
  h.setUser({ id: "other-actor", organization: { id: "other-org" } });
  assert.equal(h.render("new").workspace, "");
  assert.equal(h.calls[0].signal.aborted, true);
  await h.complete(1, ["new"]);
  const scope = h.render("new").scope;
  await h.complete(0, ["old"]);
  assert.equal(h.render("new").workspace, "new");
  assert.equal(h.render("new").scope, scope);
  h.render("next");
  assert.equal(h.render("next").workspace, "");
  await h.complete(2, ["next"]);
  assert.equal(h.render("next").workspace, "next");
});

test("creation retries preserve the intent key and workspace; changed payload conflicts remain visible", async () => {
  const fetch = globalThis.fetch;
  const storage = globalThis.localStorage;
  const requests: Array<{ body: any; headers: Headers }> = [];
  globalThis.localStorage = { getItem: () => "offline-token" } as Storage;
  globalThis.fetch = async (_url, options) => {
    const body = JSON.parse(String(options?.body));
    requests.push({ body, headers: new Headers(options?.headers) });
    if (requests.length === 1) throw new Error("lost response");
    const conflict = body.name !== "Original";
    return new Response(JSON.stringify(conflict ? { detail: "Idempotency key was already used for a different campaign request" } : { ok: true, campaign: { id: "original" } }), { status: conflict ? 409 : 200 });
  };
  try {
    const create = (name = "Original") => saveCampaign("session", name, "Objective", undefined, 0, undefined, undefined, [], undefined, "stable-key", "selected");
    await assert.rejects(create());
    assert.equal(requests.length, 1); // Mutations are not automatically retried.
    assert.deepEqual(await create(), { ok: true, campaign: { id: "original" } });
    assert.deepEqual(requests[0].body, requests[1].body);
    await assert.rejects(create("Changed"), (error: any) => error instanceof ApiError && error.status === 409);
    assert.equal(requests.length, 3);
    for (const request of requests) {
      assert.equal(request.body.idempotency_key, "stable-key");
      assert.equal(request.headers.get("X-Workspace-Id"), "selected");
      assert.equal(request.headers.get("Authorization"), "Bearer offline-token");
    }
  } finally { globalThis.fetch = fetch; globalThis.localStorage = storage; }
});

test("campaign pages use the campaign-only scope adapter and retain duplicate-submit and retry guards", async () => {
  const create = await readFile(new URL("../app/(dashboard)/campaigns/new/page.tsx", import.meta.url), "utf8");
  const detail = await readFile(new URL("../app/(dashboard)/campaigns/[id]/page.tsx", import.meta.url), "utf8");
  const hook = await readFile(new URL("../hooks/useCampaignWorkspace.ts", import.meta.url), "utf8");
  assert.doesNotMatch(hook, /discovery-context|useIntelligenceWorkspace|sessionStorage|localStorage/);
  assert.doesNotMatch(create, /discovery-context|useIntelligenceWorkspace/);
  for (const page of [create, detail]) {
    assert.match(page, /useCampaignWorkspace\(/);
    assert.doesNotMatch(page, /useIntelligenceWorkspace/);
    assert.match(page, /onClick=\{context.retry\}/);
  }
  // Source-boundary guards complement the behavioral adapter/API tests above.
  assert.match(create, /useRef\(searchParams\?\.get\("creation_key"\)/);
  assert.match(create, /if \(savingRef.current\) return/);
  assert.match(create, /savingRef.current = true/);
  assert.match(create, /savingRef.current = false/);
  assert.match(create, /creationKey.current,\s*workspaceId,/);
  assert.match(create, /const selectedIds = searchParams.get\("lead_ids"\)/);
  assert.match(create, /new Set\(selectedIds.split\(","\)/);
  assert.match(create, /selectedLeads,\s*discoveryId \|\| undefined/);
  assert.match(create, /objective.trim\(\)/);
  assert.match(create, /key=\{`\$\{context.scope\}:\$\{params.get\("lead_ids"\)/);
  assert.match(detail, /key=\{`\$\{context.scope\}:\$\{campaignId\}`\}/);
});

test("actual standalone campaign form requires description and retries with its original intent", async () => {
  const source = await readFile(new URL("../app/(dashboard)/campaigns/new/page.tsx", import.meta.url), "utf8");
  const slots: any[] = [];
  let cursor = 0;
  let rejectFirst: (error: Error) => void = () => { throw new Error("First request not started"); };
  const calls: any[][] = [];
  const pushed: string[] = [];
  const replacements: string[] = [];
  const exports: any = {};
  const element = (type: any, props: any, ...children: any[]) => ({ type, props: { ...props, children } });
  const react = {
    createElement: element,
    useEffect() {}, // No Discovery handoff is present in this campaign-only case.
    useRef(initial: any) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial: any) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value: any) => { slots[index] = value; }];
    },
  };
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText, {
    exports, React: react, URL, Error,
    crypto: { randomUUID: () => "new-intent" },
    localStorage: { getItem: () => "offline-session" },
    sessionStorage: { removeItem() {} },
    window: { location: { href: "http://offline.invalid/campaigns/new?workspace_id=selected" }, history: { state: null, replaceState: (_state: any, _title: string, url: string) => replacements.push(url) } },
    require(name: string) {
      if (name === "react") return react;
      if (name === "next/navigation") return { useRouter: () => ({ push: (url: string) => pushed.push(url) }), useSearchParams: () => new URLSearchParams("workspace_id=selected") };
      if (name.endsWith("hooks/useCampaignWorkspace")) return { useCampaignWorkspace: () => ({ workspace: "selected", scope: "actor:selected" }) };
      if (name.endsWith("lib/api")) return { saveCampaign: (...args: any[]) => {
        calls.push(args);
        return calls.length === 1 ? new Promise((_resolve, reject) => { rejectFirst = reject; }) : Promise.resolve({ ok: true, campaign: { id: "recovered" } });
      } };
      if (name.endsWith("lib/client-cache")) return { invalidateClientCache() {}, scopedKey: (...parts: string[]) => parts.join(":") };
      if (name.endsWith("shared/Toast")) return { toast() {} };
      if (name.endsWith("layout/WorkspaceContainer") || name.endsWith("primitives/AppPage")) return { default: "container" };
      throw new Error(`Unexpected campaign form dependency: ${name}`);
    },
  });
  const form = exports.default();
  const render = () => { cursor = 0; return form.type(form.props); };
  const find = (node: any, type: string): any => {
    if (!node || typeof node !== "object") return undefined;
    if (node.type === type) return node;
    for (const child of node.props?.children?.flat(Infinity) || []) {
      const result = find(child, type);
      if (result) return result;
    }
  };
  let tree = render();
  assert.equal(find(tree, "input").props.required, true);
  assert.equal(find(tree, "textarea").props.required, true);
  find(tree, "input").props.onChange({ target: { value: "Campaign" } });
  await find(render(), "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls.length, 0); // A name alone must never create a campaign.
  find(tree, "textarea").props.onChange({ target: { value: "Objective" } });
  tree = render();
  assert.equal(find(tree, "input").props.value, "Campaign");
  assert.equal(find(tree, "textarea").props.value, "Objective");
  const submit = find(tree, "form").props.onSubmit;
  const first = submit({ preventDefault() {} });
  await submit({ preventDefault() {} });
  assert.equal(calls.length, 1);
  rejectFirst(new Error("lost response"));
  await first;
  await find(render(), "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[1][1], "Campaign");
  assert.equal(calls[1][2], "Objective");
  assert.equal(calls[1][4], 0);
  assert.equal(calls[1][7].length, 0);
  assert.equal(calls[1][9], "new-intent");
  assert.equal(calls[1][10], "selected");
  assert.equal(replacements.length, 1);
  assert.equal(new URL(replacements[0]).searchParams.get("creation_key"), "new-intent");
  assert.deepEqual(pushed, ["/campaigns/recovered?workspace_id=selected"]);
});

test("Discovery creation navigates to the universal form with canonical IDs and does not create a campaign inline", async () => {
  const source = await readFile(new URL("../components/dashboard/DiscoveryCampaignActions.tsx", import.meta.url), "utf8");
  const pushed: string[] = [];
  const exports: any = {};
  const react = {
    createElement: (type: any, props: any, ...children: any[]) => ({ type, props: { ...props, children } }),
    useState: (initial: any) => [initial, () => {}],
    useRef: (initial: any) => ({ current: initial }),
    useEffect() {},
  };
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText, {
    exports, React: react, URLSearchParams,
    require(name: string) {
      if (name === "react") return react;
      if (name === "next/navigation") return { useRouter: () => ({ push: (url: string) => pushed.push(url) }) };
      if (name === "next/link") return { default: "link" };
      if (name.endsWith("lib/api")) return new Proxy({}, { get: () => () => { throw new Error("Creation handoff must not call an API"); } });
      if (name.endsWith("campaign-attachment-reconciliation")) return {};
      throw new Error(`Unexpected Discovery creation dependency: ${name}`);
    },
  });
  const tree = exports.default({ leadIds: ["lead-1", "lead-2"], campaignContext: null, workspaceId: "selected", onComplete() { throw new Error("Selection must survive navigation"); }, onBusy() {} });
  const buttons = (node: any): any[] => {
    if (!node || typeof node !== "object") return [];
    return [...(node.type === "button" ? [node] : []), ...(node.props?.children?.flat(Infinity) || []).flatMap(buttons)];
  };
  const create = buttons(tree).find(button => button.props.children.includes("Create campaign with selected leads"));
  assert.ok(create);
  create.props.onClick();
  assert.equal(pushed.length, 1);
  const url = new URL(pushed[0], "http://offline.invalid");
  assert.equal(url.pathname, "/campaigns/new");
  assert.equal(url.searchParams.get("workspace_id"), "selected");
  assert.equal(url.searchParams.get("lead_ids"), "lead-1,lead-2");
  assert.equal(url.searchParams.get("return"), "discovery");
  assert.doesNotMatch(source, /New campaign name|saveCampaign|createSelectedCampaign/);
});
