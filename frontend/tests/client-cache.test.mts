/**
 * PR-3C — client data cache regression tests.
 *
 * Covers the 13 mandated cases:
 *   1  miss → network            2  fresh hit → no network
 *   3  stale → cached + revalidate
 *   4  simultaneous consumers → one request
 *   5  background refresh running → no duplicate
 *   6  mutation invalidation     7  logout clears cache
 *   8  user change isolation     9  workspace scoping
 *   10 refresh failure keeps cached content visible
 *   11 initial failure → error propagates
 *   12 TTL expiry                13 bounded memory / eviction
 *
 * Run: node tests/client-cache.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";

// The module touches localStorage only inside debugEnabled(); provide a stub
// global so it can be imported in Node.
(globalThis as any).localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

const { swrFetch, peekCache, scopedKey, invalidateClientCache, clearClientCache, __testReset, __testAgeEntry }
  = await import("../lib/client-cache.ts");

function reset() {
  __testReset();
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test("1. miss → network fetch executes", async () => {
  reset();
  let calls = 0;
  const value = await swrFetch("k", async () => { calls += 1; return { n: calls }; });
  assert.equal(calls, 1);
  assert.deepEqual(value, { n: 1 });
});

test("2. fresh hit (<10s) → immediate cached response, no network", async () => {
  reset();
  let calls = 0;
  const key = scopedKey("sess-1", "campaigns");
  await swrFetch(key, async () => { calls += 1; return [{ id: "c1" }]; });
  const second = await swrFetch(key, async () => { calls += 1; return []; });
  assert.equal(calls, 1);
  assert.deepEqual(second, [{ id: "c1" }]);
});

test("3. stale (≥10s) → cached served via onStale + background revalidate via onUpdate", async () => {
  reset();
  const key = scopedKey("s", "campaigns");
  await swrFetch(key, async () => [{ id: "old" }]);
  __testAgeEntry(key, 11); // past the 10s TTL

  let staleSeen: any = null;
  let freshSeen: any = null;
  let calls = 0;
  const value = await swrFetch(
    key,
    async () => { calls += 1; return [{ id: "new" }]; },
    { onStale: v => { staleSeen = v; }, onUpdate: v => { freshSeen = v; } },
  );
  assert.equal(staleSeen[0].id, "old");   // rendered instantly from cache
  assert.equal(calls, 1);                  // background revalidation ran
  assert.equal(freshSeen[0].id, "new");   // silent update delivered
  assert.equal(value[0].id, "new");
});

test("4. simultaneous consumers → one network request", async () => {
  reset();
  let calls = 0;
  const fetcher = async () => { calls += 1; return "data"; };
  const [a, b] = await Promise.all([
    swrFetch("shared", fetcher),
    swrFetch("shared", fetcher),
  ]);
  assert.equal(calls, 1);
  assert.equal(a, "data") ;
  assert.equal(b, "data");
});

test("5. background refresh already running → no duplicate request on remount", async () => {
  reset();
  const gate = deferred<void>();
  let calls = 0;
  const fetcher = async () => { calls += 1; await gate.promise; return "slow"; };

  const first = swrFetch("bg", async () => fetcher());        // starts request
  await new Promise(r => setTimeout(r, 0));                    // let inflight register
  const second = swrFetch("bg", async () => fetcher());       // must dedupe
  gate.resolve();                                              // unblock the single request
  const [a, b] = await Promise.all([first, second]);
  assert.equal(calls, 1);
  assert.equal(a, "slow");
  assert.equal(b, "slow");
});

test("6. successful mutation → invalidateClientCache forces refetch", async () => {
  reset();
  const key = scopedKey("s", "campaigns");
  await swrFetch(key, async () => [{ id: "before-mutation" }]);
  invalidateClientCache(key);
  const value = await swrFetch(key, async () => [{ id: "after-mutation" }]);
  assert.deepEqual(value, [{ id: "after-mutation" }]);
});

test("7. logout → clearClientCache wipes everything", async () => {
  reset();
  await swrFetch(scopedKey("user-a-session", "campaigns"), async () => ["a"]);
  clearClientCache(); // called by AuthContext.clearStoredTokens()
  assert.equal(peekCache(scopedKey("user-a-session", "campaigns")), null);
});

test("8. user change → old user's cache cannot be shown", async () => {
  reset();
  const keyA = scopedKey("session-A", "campaigns");
  await swrFetch(keyA, async () => [{ owner: "A" }]);
  // Simulate identity switch: session B uses a different scoped key and the
  // auth boundary cleared everything anyway.
  clearClientCache();
  const keyB = scopedKey("session-B", "campaigns");
  const value = await swrFetch(keyB, async () => [{ owner: "B" }]);
  assert.deepEqual(value, [{ owner: "B" }]);
  assert.equal(peekCache(keyA), null);
});

test("9. workspace scoping → distinct keys never collide", async () => {
  reset();
  const ws1 = scopedKey("sess", "drafts", "ws-1");
  const ws2 = scopedKey("sess", "drafts", "ws-2");
  await swrFetch(ws1, async () => [{ ws: 1 }]);
  await swrFetch(ws2, async () => [{ ws: 2 }]);
  assert.notDeepEqual(await swrFetch(ws1, async () => []), []);
  assert.equal((await swrFetch(ws1, async () => []) as any)[0].ws, 1);
  assert.equal((await swrFetch(ws2, async () => []) as any)[0].ws, 2);
});

test("10. failed background refresh keeps cached content", async () => {
  reset();
  const key = scopedKey("s", "campaigns");
  await swrFetch(key, async () => [{ id: "cached" }]);
  __testAgeEntry(key, 11); // stale

  let staleSeen: any = null;
  let errorEscaped = false;
  try {
    await swrFetch(key, async () => { throw new Error("network down"); },
      { onStale: v => { staleSeen = v; } });
  } catch {
    errorEscaped = true;
  }
  assert.equal(errorEscaped, false, "swrFetch should surface errors to caller, not swallow");
  assert.equal(staleSeen[0].id, "cached");
  // Cached entry remains for continued display.
  assert.equal(peekCache<any>(key)!.value[0].id, "cached");
});

test("11. initial failure → error propagates (existing behavior preserved)", async () => {
  reset();
  await assert.rejects(
    swrFetch("never-cached", async () => { throw new Error("boom"); }),
    /boom/,
  );
  // And nothing was cached from a failed fetch.
  assert.equal(peekCache("never-cached"), null);
});

test("12. TTL expiry → stale path taken at ≥10s", async () => {
  reset();
  const key = "ttl-key";
  await swrFetch(key, async () => ({ v: 1 }));
  __testAgeEntry(key, 9.9);
  let networkOnFreshHit = 0;
  await swrFetch(key, async () => { networkOnFreshHit += 1; return { v: 1 }; });
  assert.equal(networkOnFreshHit, 0, "still fresh under 10s");

  __testAgeEntry(key, 0.2); // now ≥10s total
  let revalidated = false;
  await swrFetch(key, async () => { revalidated = true; return { v: 2 }; });
  assert.equal(revalidated, true);
});

test("13. bounded memory → oldest entries evicted beyond MAX_ENTRIES", async () => {
  reset();
  // MAX_ENTRIES is 60; insert 80 distinct keys and confirm eviction kept size
  // bounded while recent entries survive.
  for (let i = 0; i < 80; i++) {
    await swrFetch(`bulk-${i}`, async () => i);
  }
  const earlyGone = peekCache("bulk-0") === null;
  const lateAlive = peekCache("bulk-79") !== null;
  assert.equal(earlyGone, true);
  assert.equal(lateAlive, true);
});
