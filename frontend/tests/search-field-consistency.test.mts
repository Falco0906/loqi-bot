import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { listWorkspaceLeads } from "../lib/api.ts";

test("canonical filtered pagination preserves IDs and incomplete-read warnings", async () => {
  const original = globalThis.fetch;
  const calls: URL[] = [];
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input)); calls.push(url);
    assert.equal(new Headers(options?.headers).get("X-Workspace-Id"), "authorized-workspace");
    return new Response(JSON.stringify({ ok: true, leads: [{ id: "canonical-workspace-lead", source_kind: "provider", source_provenance: ["csv_import", "apollo"] }], total: 51, page: 2, page_size: 50, warnings: ["Saved results unavailable"] }), { status: 200 });
  };
  try {
    const result = await listWorkspaceLeads("offline", "founders", 2, { location: "London", industry: "SaaS", company: "Acme", title: "COO", keywords: "operations" }, "run", undefined, "authorized-workspace");
    assert.equal(calls.length, 1);
    for (const [key, value] of Object.entries({ q: "founders", page: "2", location: "London", industry: "SaaS", company: "Acme", title: "COO", keywords: "operations", discovery_id: "run" })) assert.equal(calls[0].searchParams.get(key), value);
    assert.equal(result.leads[0].id, "canonical-workspace-lead");
    assert.equal(result.total, 51);
    assert.deepEqual(result.warnings, ["Saved results unavailable"]);
  } finally { globalThis.fetch = original; }
});

test("incomplete hydration is labelled without hiding available canonical rows", async () => {
  const page = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
  assert.match(page, /if \(!isCurrent\(\)\) return;\s*setWorkspaceLeads\(result.leads\)/);
  assert.match(page, /setResultWarning\(\(result.warnings \|\| \[\]\)\.join/);
  assert.match(page, /Search results are temporarily incomplete/);
  assert.match(page, /loadedScope === currentResultScope.current && resultWarning/);
  const repository = await readFile(new URL("../lib/repositories.ts", import.meta.url), "utf8");
  assert.match(repository, /recordFromJson\(metadata.provider_context\)/);
  assert.match(repository, /company: text\(imported.company\) \|\| text\(company.name\)/);
  assert.match(repository, /const id = String\(workspaceLead.id \|\| ""\);\s*if \(!id\) return null;/);
});
