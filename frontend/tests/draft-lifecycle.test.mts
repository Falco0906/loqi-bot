/**
 * Regression test: Draft Review lifecycle sections (PR — Draft Lifecycle).
 *
 * A sent draft must appear ONLY in the Sent section, must not be actionable
 * (no Approve / Send Now / Schedule), and a status can never land in two
 * buckets at once.
 *
 * Run with: node tests/draft-lifecycle.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";
import {
  draftBucket,
  isActionable,
  isApprovable,
  isSentStatus,
} from "../lib/draft-lifecycle.ts";

test("A. approved draft appears in Approved", () => {
  assert.strictEqual(draftBucket("approved"), "approved");
  assert.strictEqual(draftBucket("auto_approved"), "approved");
});

test("B. sent draft appears only in Sent", () => {
  assert.strictEqual(draftBucket("sent"), "sent");
});

test("C. sent draft has no Approve/Send/Schedule action", () => {
  assert.strictEqual(isActionable("sent"), false);
  assert.strictEqual(isApprovable("sent"), false);
  // scheduled/approved remain actionable (they can still be cancelled/sent)
  assert.strictEqual(isActionable("approved"), true);
  assert.strictEqual(isActionable("scheduled"), true);
});

test("same draft cannot appear in both Approved and Sent", () => {
  const statuses = [
    "pending",
    "needs_review",
    "approved",
    "auto_approved",
    "scheduled",
    "sent",
    "sending",
    "rejected",
    "failed",
    "cancelled",
    "archived",
  ];
  const bucketOf = new Map<string, number>();
  for (const s of statuses) {
    const b = draftBucket(s);
    if (b === null) continue;
    const key = `${s}:${b}`;
    assert.ok(
      !bucketOf.has(key),
      `${s} should map to exactly one bucket, got duplicate ${b}`,
    );
    bucketOf.set(key, 1);
  }
  // The bucket sets are pairwise disjoint — no status can straddle sections.
  const pending = statuses.filter((s) => draftBucket(s) === "pending");
  const approved = statuses.filter((s) => draftBucket(s) === "approved");
  const sent = statuses.filter((s) => draftBucket(s) === "sent");
  assert.ok(!pending.some((s) => approved.includes(s)));
  assert.ok(!approved.some((s) => sent.includes(s)));
  assert.ok(!pending.some((s) => sent.includes(s)));
});

test("sending status is treated as already-sent for action purposes", () => {
  assert.strictEqual(isSentStatus("sent"), true);
  assert.strictEqual(isSentStatus("sending"), true);
  assert.strictEqual(isSentStatus("approved"), false);
});
