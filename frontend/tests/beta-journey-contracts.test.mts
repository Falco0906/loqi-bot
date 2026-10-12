// Offline API-contract/source tests, not mounted React or browser E2E.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { importLeadCsv, listWorkspaceLeads, previewLeadCsv } from "../lib/api.ts";

test("CSV preview, confirmation and read-back use the same explicit workspace", async () => {
  const original = globalThis.fetch;
  const requests: Array<{ path: string; body: unknown }> = [];
  const rows = [{ row: 2, lead: { email: "ada@example.com", company: "Acme" } }];
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input));
    assert.equal(new Headers(options?.headers).get("X-Workspace-Id"), "selected-workspace");
    requests.push({ path: url.pathname, body: options?.body ? JSON.parse(String(options.body)) : null });
    const result = url.pathname.endsWith("csv-preview") ? { rows, valid_rows: 1, invalid_rows: [] }
      : url.pathname.endsWith("csv-import") ? { imported: 1, duplicates: [], invalid: [] }
      : { leads: [{ id: "canonical-id", company: "Acme" }], total: 1, page: 1, page_size: 50 };
    return new Response(JSON.stringify(result), { status: 200 });
  };
  try {
    const preview = await previewLeadCsv("offline", "Email,Company\nada@example.com,Acme", {}, "selected-workspace");
    assert.equal((await importLeadCsv("offline", preview.rows, "selected-workspace")).imported, 1);
    assert.equal((await listWorkspaceLeads("offline", "", 1, {}, "", undefined, "selected-workspace")).leads[0].id, "canonical-id");
    assert.equal(requests.length, 3);
    assert.deepEqual(requests[1].body, { rows });
  } finally { globalThis.fetch = original; }
});

test("import errors remain observable and never automatically repeat a mutation", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ detail: "Import unavailable" }), { status: 503 }); };
  try {
    await assert.rejects(importLeadCsv("offline", [], "workspace"), /Import unavailable/);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test("Lead Database scopes/remounts per workspace and separates CSV errors from table state", async () => {
  const page = await readFile(new URL("../app/(dashboard)/contacts/page.tsx", import.meta.url), "utf8");
  assert.match(page, /useIntelligenceWorkspace\(params.get\("workspace_id"\)/);
  assert.match(page, /ContactsWorkspace key=\{context.scope\}/);
  assert.match(page, /controller.signal, workspaceId\)/);
  assert.match(page, /if \(!current\(\)\) return;/);
  assert.match(page, /readController.current\?\.abort\(\)/);
  assert.match(page, /if \(!preview \|\| importLock.current\) return/);
  assert.match(page, /setActionError\(errorMessage\(importError/);
  assert.match(page, /setSearch\(""\); setPage\(1\); await load\(1, ""\)/);
  assert.match(page, /setSelected\(new Set\(\)\); \}, \[search\]\)/);
  const confirmation = page.slice(page.indexOf("const confirm ="), page.indexOf("const allVisible ="));
  assert.doesNotMatch(confirmation, /setError\(/);
});

test("Draft Review can clear a subject and reflects the canonical pending edit state", async () => {
  const page = await readFile(new URL("../components/draft/DraftReviewWorkspace.tsx", import.meta.url), "utf8");
  const edit = page.slice(page.indexOf("async function saveEdit"), page.indexOf("async function handleRefine"));
  assert.ok(edit.includes('const full = `Subject: ${editSubject}\\n\\n${editBody}`;'));
  assert.match(edit, /subject: editSubject, text: editBody, status: "pending"/);
  assert.match(edit, /await updateDraft/);
  assert.doesNotMatch(edit, /sendDraft|scheduleDraft|generate/);
});
