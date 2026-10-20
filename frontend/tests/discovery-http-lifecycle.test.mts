/** Offline execution of the real API client; fetch is never allowed onto a socket. */
import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import { setImmediate as flush } from "node:timers/promises";
import { ApiError, listWorkspaceLeads } from "../lib/api.ts";

function install(t: TestContext, fetcher: typeof fetch) {
  t.mock.method(globalThis, "fetch", fetcher);
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: () => "synthetic-session",
  } });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
}

test("GET retries two transport failures at 500ms and 1000ms, preserving scope", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls: RequestInit[] = [];
  install(t, async (_url, options) => {
    calls.push(options!);
    if (calls.length < 3) throw new TypeError("Synthetic disconnected transport");
    return Response.json({ ok: true, leads: [], total: 0, page: 1, page_size: 50 });
  });
  const pending = listWorkspaceLeads("synthetic", "COO", 1, {}, "", undefined, "workspace-A");
  await flush();
  assert.equal(calls.length, 1);
  t.mock.timers.tick(499); await flush();
  assert.equal(calls.length, 1);
  t.mock.timers.tick(1); await flush();
  assert.equal(calls.length, 2);
  t.mock.timers.tick(999); await flush();
  assert.equal(calls.length, 2);
  t.mock.timers.tick(1);
  assert.equal((await pending).total, 0);
  assert.equal(calls.length, 3);
  for (const options of calls) {
    assert.equal(new Headers(options.headers).get("X-Workspace-Id"), "workspace-A");
    assert.equal(new Headers(options.headers).get("Authorization"), "Bearer synthetic-session");
  }
});

test("cancelling during GET backoff prevents the next attempt", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  install(t, async () => { calls++; throw new TypeError("Synthetic disconnected transport"); });
  const controller = new AbortController();
  const pending = listWorkspaceLeads("synthetic", "COO", 1, {}, "", controller.signal, "workspace-A");
  const rejected = assert.rejects(pending, error => error instanceof DOMException && error.name === "AbortError");
  await flush();
  assert.equal(calls, 1);
  controller.abort();
  t.mock.timers.tick(500);
  await rejected;
  t.mock.timers.tick(20_000); await flush();
  assert.equal(calls, 1);
});

for (const status of [401, 429, 503]) {
  test(`HTTP ${status} is not retried as a transport failure`, async t => {
    let calls = 0;
    install(t, async () => { calls++; return Response.json({ detail: "Synthetic HTTP rejection" }, { status }); });
    await assert.rejects(listWorkspaceLeads("synthetic", "COO", 1, {}, "", undefined, "workspace-A"),
      error => error instanceof ApiError && error.status === status);
    assert.equal(calls, 1);
  });
}
