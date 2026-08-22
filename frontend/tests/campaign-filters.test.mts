/**
 * PR-3D-FIX — campaigns search/filter false-empty regression tests.
 *
 * Run: node tests/campaign-filters.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";

const { filterCampaigns, canonicalTotal, shouldShowNoMatches, normalizeQuery }
  = await import("../lib/campaign-filters.ts");

const CAMPAIGNS = [
  { id: "1", name: "Q3 Fintech Outreach", objective: "Series A founders", status: "strategy" },
  { id: "2", name: "Healthcare SaaS", objective: "Hospital CTOs", status: "active" },
  { id: "3", name: "Archived Legacy", objective: "old list", status: "archived" },
];

test("A. empty query + existing campaigns → all non-deleted shown", () => {
  const visible = filterCampaigns(CAMPAIGNS, "");
  assert.equal(visible.length, 3);
  assert.equal(canonicalTotal(CAMPAIGNS), 3);
});

test("A2. whitespace-only query behaves like empty", () => {
  assert.equal(normalizeQuery("   "), "");
  assert.equal(filterCampaigns(CAMPAIGNS, "   ").length, 3);
});

test("B. non-empty query + zero matches → no-match state is valid", () => {
  const filtered = filterCampaigns(CAMPAIGNS, "zzz-no-match");
  assert.equal(filtered.length, 0);
  assert.equal(
    shouldShowNoMatches({
      authoritativeDataLoaded: true,
      canonicalCount: canonicalTotal(CAMPAIGNS),
      query: "zzz-no-match",
      filteredCount: filtered.length,
    }),
    true,
  );
});

test("F. filtering never mutates the canonical array", () => {
  const canonical = [...CAMPAIGNS];
  const snapshot = JSON.stringify(canonical);
  filterCampaigns(canonical, "healthcare");
  assert.equal(JSON.stringify(canonical), snapshot);
});

test("G. count stays canonical while filtering", () => {
  const filtered = filterCampaigns(CAMPAIGNS, "fintech");
  assert.equal(filtered.length, 1);
  assert.equal(canonicalTotal(CAMPAIGNS), 3, "header must show canonical total");
});

test("deleted campaigns are excluded from both views", () => {
  const withDeleted = [...CAMPAIGNS, { id: "4", name: "Dead", status: "deleted" }];
  assert.equal(filterCampaigns(withDeleted, "").length, 3);
  assert.equal(canonicalTotal(withDeleted), 3);
});

test("matches hit name OR objective, case-insensitively", () => {
  assert.equal(filterCampaigns(CAMPAIGNS, "FINTECH").length, 1);
  assert.equal(filterCampaigns(CAMPAIGNS, "hospital ctos").length, 1);
});
