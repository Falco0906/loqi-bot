/**
 * PR-3D — navigation state regression tests.
 *
 * Covers: set/get, one-shot take, TTL expiry, bounded memory, per-route
 * clearing, full clear on logout, isolation between resources.
 *
 * Run: node tests/nav-state.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";

(globalThis as any).localStorage = { getItem: () => null, setItem(){}, removeItem(){} };

const {
  setNavState, getNavState, takeNavState,
  clearNavState, navKey,
} = await import("../lib/nav-state.ts");

test("set/get roundtrip", () => {
  setNavState("inbox", "lastOpened", { id: "conv-1", at: Date.now() });
  assert.deepEqual(getNavState("inbox", "lastOpened"), { id: "conv-1", at: Date.now() });
});

test("unset key returns null (UNKNOWN ≠ EMPTY at state level)", () => {
  assert.equal(getNavState("inbox", "never-set"), null);
});

test("takeNavState is one-shot", () => {
  setNavState("draft-review", "oneShot", "x");
  assert.equal(takeNavState("draft-review", "oneShot"), "x");
  assert.equal(getNavState("draft-review", "oneShot"), null);
});

test("resources are isolated from each other", () => {
  setNavState("campaign", "selected", { id: "c1" });
  setNavState("discovery", "selected", { id: "d1" });
  assert.deepEqual(getNavState("campaign", "selected").id, "c1");
  assert.deepEqual(getNavState("discovery", "selected").id, "d1");
  clearNavState("campaign");
  assert.equal(getNavState("campaign", "selected"), null);
  assert.equal(getNavState("discovery", "selected").id, "d1"); // untouched
});

test("clearNavState() with no arg wipes everything (logout)", () => {
  setNavState("inbox", "lastOpened", { id: "x" });
  setNavState("campaign", "selected", { id: "y" });
  clearNavState();
  assert.equal(getNavState("inbox", "lastOpened"), null);
  assert.equal(getNavState("campaign", "selected"), null);
});

test("TTL expiry self-heals", async () => {
  setNavState("ttl-test", "field", "v", 10); // 10ms ttl
  await new Promise(r => setTimeout(r, 25));
  assert.equal(getNavState("ttl-test", "field"), null);
});

test("bounded memory: oldest entries evicted beyond cap", () => {
  // NAV_MAX_ENTRIES = 100; insert 150 distinct keys
  for (let i = 0; i < 150; i++) setNavState(`bulk-${i}`, "f", i);
  assert.equal(getNavState("bulk-0", "f"), null);       // evicted
  assert.equal(getNavState("bulk-149", "f"), 149);      // recent survives
});
