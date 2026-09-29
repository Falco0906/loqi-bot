import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const discovery = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
const legacyDiscover = await readFile(new URL("../app/(dashboard)/discover/page.tsx", import.meta.url), "utf8");
const contacts = await readFile(new URL("../app/(dashboard)/contacts/page.tsx", import.meta.url), "utf8");

test("Discovery renders one server-paginated canonical result set for workspace and provider leads", () => {
  for (const text of ["Search people, companies, titles, websites", "Search all sources", "Clear all", "Analyze with Loqi", "Lead results pagination", "Could not load leads", "Research history"]) {
    assert.ok(discovery.includes(text), `missing ${text}`);
  }
  assert.match(discovery, /lead_ids=\$\{encodeURIComponent\(\[\.\.\.selected\]\.join/);
  assert.match(discovery, /listWorkspaceLeads\(\s*activeSessionToken\(\), query, page, filters, providerDiscoveryId/);
  assert.match(discovery, /startDiscoverySearch\(requestedQuery, "manual"\)/);
  assert.match(discovery, /workspaceLeadResults/);
  assert.match(discovery, /source_label/);
  assert.match(discovery, /workspaceLeads\.forEach\(\(lead\)/);
  assert.doesNotMatch(discovery, /const providerLeads/);
  assert.doesNotMatch(discovery, /const unifiedLeads/);
  assert.doesNotMatch(discovery, /create_search_run|Apollo|SerpAPI/);
  assert.match(discovery, /parseDiscoveryMode\(params\).*campaign_attach/s, "campaign provider handoff must retain its existing route");
  assert.match(legacyDiscover, /redirect\("\/discovery"\)/, "the duplicate /discover route must only redirect");
});

test("Lead Database makes CSV outcomes visible and does not retry an import", () => {
  for (const text of ["Upload CSV", "Review column mapping", "Confirm import", "Import complete:", "duplicates skipped", "No rows were retried automatically", "Loading durable lead records", "Lead database pagination"]) {
    assert.ok(contacts.includes(text), `missing ${text}`);
  }
  assert.match(contacts, /await inspect\(content, \{\}\)/, "a normally mapped CSV should preview immediately");
  assert.doesNotMatch(contacts, /Apollo|SerpAPI|OpenAI|generate/);
});
