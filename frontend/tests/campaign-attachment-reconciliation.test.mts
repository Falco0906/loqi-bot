import assert from "node:assert/strict";
import test from "node:test";
import {
  campaignContainsLeadIds,
  campaignHasAttachedDiscovery,
} from "../lib/campaign-attachment-reconciliation.ts";

test("campaign attachment reconciliation requires every selected canonical lead", () => {
  const campaign = { leads: [{ id: "lead-a" }, { id: "lead-b" }] };
  assert.equal(campaignContainsLeadIds(campaign, ["lead-a", "lead-b"]), true);
  assert.equal(campaignContainsLeadIds(campaign, ["lead-a", "lead-c"]), false);
});

test("bulk discovery attachment reconciliation uses the canonical discovery link", () => {
  assert.equal(campaignHasAttachedDiscovery({ discovery_id: "discovery-1" }, "discovery-1"), true);
  assert.equal(campaignHasAttachedDiscovery({ discovery_id: "discovery-2" }, "discovery-1"), false);
});
