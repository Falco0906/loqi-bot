import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const discovery = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
const legacyDiscover = await readFile(new URL("../app/(dashboard)/discover/page.tsx", import.meta.url), "utf8");
const contacts = await readFile(new URL("../app/(dashboard)/contacts/page.tsx", import.meta.url), "utf8");

test("Discovery starts as an explicit universal search and keeps provider results canonical", () => {
  for (const text of [
    "Who are you looking for?",
    "Describe the leads you're looking for...",
    "Find SaaS founders in the US",
    "Find heads of sales at growing startups",
    "Find operations leaders at e-commerce companies",
    "Search history",
    "DiscoveryExecutionPanel",
    "DiscoveryResearchBriefing",
    "Analyze with Loqi",
    "Lead results pagination",
  ]) {
    assert.ok(discovery.includes(text), `missing ${text}`);
  }
  assert.match(discovery, /lead_ids=\$\{encodeURIComponent\(\[\.\.\.selected\]\.join/);
  assert.match(discovery, /if \(!hasSearch\).*setWorkspaceLeads/s, "opening Discover must not fetch/list leads");
  assert.match(discovery, /listWorkspaceLeads\(activeSessionToken\(\), query, page, filters, providerDiscoveryId\)/);
  assert.match(discovery, /startDiscoverySearch\(nextQuery, "manual"\)/);
  assert.match(discovery, /provider_discovery/);
  assert.match(discovery, /source_label/);
  assert.match(discovery, /workspaceLeads\.forEach\(\(lead\)/);
  assert.match(discovery, /const FILTERS = \[/);
  assert.doesNotMatch(discovery, /Search all sources/);
  assert.doesNotMatch(discovery, /Company size/);
  assert.doesNotMatch(discovery, /Saved searches/);
  assert.doesNotMatch(discovery, /const providerLeads/);
  assert.doesNotMatch(discovery, /const unifiedLeads/);
  assert.doesNotMatch(discovery, /href=\{`\/discovery\/\$\{encodeURIComponent\(discoveryId\)\}`\}/, "provider search must not route to the research detail page");
  assert.doesNotMatch(discovery, /create_search_run|Apollo|SerpAPI/);
  assert.match(discovery, /parseDiscoveryMode\(params\).*campaign_attach/s, "campaign provider handoff must retain its existing route");
  assert.match(legacyDiscover, /redirect\("\/discovery"\)/, "the duplicate /discover route must only redirect");
});

test("Discover reuses the durable run cards instead of making a second progress or ICP view", async () => {
  const detail = await readFile(new URL("../components/dashboard/DiscoveryDetailWorkspace.tsx", import.meta.url), "utf8");
  const topbar = await readFile(new URL("../components/layout/Topbar.tsx", import.meta.url), "utf8");

  assert.match(detail, /export function DiscoveryExecutionPanel/);
  assert.match(detail, /export function DiscoveryResearchBriefing/);
  assert.match(detail, /Searching for: \{view\.query\}/);
  assert.match(detail, /View interpreted ICP and target criteria/);
  assert.match(topbar, /hideWorkspaceSearch: true/);
  assert.match(topbar, /!config\.hideWorkspaceSearch/);
});

test("Lead Database makes CSV outcomes visible and does not retry an import", () => {
  for (const text of ["Upload CSV", "Review column mapping", "Confirm import", "Import complete:", "duplicates skipped", "No rows were retried automatically", "Loading durable lead records", "Lead database pagination"]) {
    assert.ok(contacts.includes(text), `missing ${text}`);
  }
  assert.match(contacts, /await inspect\(content, \{\}\)/, "a normally mapped CSV should preview immediately");
  assert.doesNotMatch(contacts, /Apollo|SerpAPI|OpenAI|generate/);
});
