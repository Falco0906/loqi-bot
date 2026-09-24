import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const discover = await readFile(new URL("../app/(dashboard)/discover/page.tsx", import.meta.url), "utf8");
const contacts = await readFile(new URL("../app/(dashboard)/contacts/page.tsx", import.meta.url), "utf8");

test("Discover preserves URL-backed search, filter, pagination, and selected lead IDs", () => {
  for (const text of ["Search people, companies, titles, websites", "Clear all", "Analyze with Loqi", "Lead results pagination", "Could not load leads"]) {
    assert.ok(discover.includes(text), `missing ${text}`);
  }
  assert.match(discover, /lead_ids=\$\{encodeURIComponent\(\[\.\.\.selected\]\.join/);
  assert.match(discover, /listWorkspaceLeads\(token\(\), q, page, filters\)/);
  assert.doesNotMatch(discover, /create_search_run|\/api\/jobs\/search|Apollo|SerpAPI/);
});

test("Lead Database makes CSV outcomes visible and does not retry an import", () => {
  for (const text of ["Upload CSV", "Inspect columns", "Confirm import", "Import complete:", "duplicates skipped", "No rows were retried automatically"]) {
    assert.ok(contacts.includes(text), `missing ${text}`);
  }
  assert.doesNotMatch(contacts, /Apollo|SerpAPI|OpenAI|generate/);
});
