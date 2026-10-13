import assert from "node:assert/strict";
import { test } from "node:test";
import { terminalDiscoveryMessage } from "../lib/discovery-status.ts";

test("a persistence failure explicitly distinguishes saved partial rows from completion", () => {
  const message = terminalDiscoveryMessage({ status: "failed", failure: { kind: "persistence" } });
  assert.match(message, /could not finish saving/);
  assert.match(message, /may be incomplete/);
  assert.match(message, /saved leads in this workspace/);
  assert.match(message, /do not mean the search completed/);
});

test("timeout, stopped, and unknown failures never claim there were no leads", () => {
  for (const run of [
    { status: "cancelled" },
    { status: "failed", failure: { kind: "timeout" } },
    { status: "failed", failure: { kind: "execution" } },
  ]) {
    const message = terminalDiscoveryMessage(run);
    assert.match(message, /saved leads in this workspace/);
    assert.doesNotMatch(message, /no leads|no matches|successful/);
  }
});
