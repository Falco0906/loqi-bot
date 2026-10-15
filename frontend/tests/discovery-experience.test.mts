import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import ts from "typescript";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { qualificationFromPersistedMetadata } from "../lib/discovery-qualification.ts";

async function loadModule(path: string, dependencies: Record<string, unknown>) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const exports: Record<string, any> = {};
  runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022,
  } }).outputText, {
    exports, console, setTimeout, clearTimeout, React,
    localStorage: { getItem: () => "offline-session" },
    window: { localStorage: { getItem: () => "offline-session" } },
    require(name: string) { return dependencies[name] || {}; },
  });
  return exports;
}

test("workspace lead cards keep canonical IDs, own company facts and real assessment scores", async () => {
  const repo = await loadModule("../lib/repositories.ts", {
    "./discovery-qualification": { qualificationFromPersistedMetadata },
  });
  const card = repo.workspaceLeadToRecommendation({
    id: "canonical-own", first_name: "Alice", title: "Founder", email: "alice@example.test",
    metadata: { csv_import: { company: "Own company", location: "United States" }, qualification: {
      final_score: 0, highlights: ["Saved role matches target"],
      prospect_evidence: [{ field: "title", value: "Founder" }],
    } },
  }, 0);
  assert.equal(card.id, "canonical-own");
  assert.equal(card.company, "Own company");
  assert.equal(card.location, "United States");
  assert.equal(card.match, 0, "a real zero score must not become an invented fallback score");
  assert.equal(card.reasoning, "Saved role matches target");
  assert.equal(card.qualification.prospect_evidence[0].value, "Founder");
  assert.equal(card.buyingSignal, "No additional buying signal recorded");
});

test("completed workspace research keeps every contact card and a truthful research-complete summary", async () => {
  const repo = await loadModule("../lib/repositories.ts", {
    "./discovery-qualification": { qualificationFromPersistedMetadata },
    "./api": { getDiscovery: async () => ({ discovery: {
      id: "run", status: "completed", query: "Find SaaS founders", metadata: { search_scope: "workspace" },
      discovery_companies: [{ company_id: "company", company: { id: "company", name: "Own company" } }],
      discovery_leads: ["one", "two"].map(id => ({ workspace_lead: {
        id, company_id: "company", first_name: id, title: "Founder", metadata: { csv_import: { company: "Own company" } },
      } })),
    } }) },
  });
  const view = await repo.fetchDiscovery("run", "workspace");
  assert.equal(view.narrativeTitle, "Research complete");
  assert.match(view.narrativeLines[0], /2 saved leads in this workspace/);
  assert.equal(view.recommendations.length, 2, "company grouping must not swallow a second contact");
  assert.equal(view.recommendations[0].id, "one");
  assert.equal(view.recommendations[1].id, "two");
});

test("existing research-complete and expanded lead-detail components render the restored content", async () => {
  const components = await loadModule("../components/dashboard/DiscoveryDetailWorkspace.tsx", { react: React });
  const view = { query: "Find founders", narrativeTitle: "Research complete", narrativeLines: ["2 saved leads matched."], companyCount: 1 };
  const summary = renderToStaticMarkup(React.createElement(components.DiscoveryResearchBriefing, { view, resultCount: 2 }));
  assert.match(summary, /Search intelligence/);
  assert.match(summary, /Research complete/);
  assert.match(summary, /2 saved leads matched/);
  const details = renderToStaticMarkup(React.createElement(components.DiscoveryLeadDetails, {
    rec: { reasoning: "Saved role matches target", buyingSignal: "Unknown", signalDetail: "No signal recorded", funding: "—", hiring: "—" },
    selected: false, onToggle() {},
  }));
  assert.match(details, /Executive Deep Reasoning/);
  assert.match(details, /Saved role matches target/);
  assert.match(details, /Select for campaign/);
  const page = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
  assert.match(page, /Find SaaS founders in the US/);
  assert.match(page, /Describe the leads you're looking for/);
  assert.match(page, /providerRun\?\.status === "completed" && \(\s*<DiscoveryResearchBriefing/);
  assert.doesNotMatch(page, /Search completed over this workspace|Searching saved leads in this workspace/);
  assert.match(page, /<DiscoveryLeadDetails/);
  assert.match(page, /DiscoveryCampaignActions/);
  assert.doesNotMatch(page, /Analyze with Loqi|lead-intelligence/);
});

test("research card collapses the ICP by default while keeping applied filters visible", async () => {
  const components = await loadModule("../components/dashboard/DiscoveryDetailWorkspace.tsx", { react: React });
  const plan = {
    offering: "", primaryServices: [], targetAudience: "SaaS founders", industries: ["SaaS"], subIndustries: [],
    icpSummary: "Founders of SaaS companies in the United States", buyerPersonas: [], companyKeywords: [],
    decisionMakerRoles: ["Founder"], negativeKeywords: [], painPoints: [], buyingSignals: [], technologies: [],
    businessCharacteristics: [], exclusions: [], geography: ["United States"], companySize: ["Small businesses"],
    messagingAngle: "", successCriteria: "",
  };
  const view = {
    query: "Find SaaS founders in the US", narrativeTitle: "Research complete", narrativeLines: ["2 saved leads matched."],
    companyCount: 1, plan, metadata: { search_scope: "workspace", ui_filters: { industry: "SaaS", location: "United States", keywords: "", title: null, unknown: "not a filter" } },
  };
  const html = renderToStaticMarkup(React.createElement(components.DiscoveryResearchBriefing, { view, resultCount: 2 }));
  assert.match(html, /Ideal customer profile \(ICP\)/);
  assert.match(html, /Founders of SaaS companies in the United States/);
  const disclosure = html.match(/<details\b[^>]*>[\s\S]*?<\/details>/)?.[0];
  assert.ok(disclosure, "the ICP must be collapsible");
  assert.doesNotMatch(disclosure, /<details[^>]*\bopen\b/, "the ICP starts collapsed");
  assert.match(disclosure, /Founders of SaaS companies in the United States/);
  assert.doesNotMatch(disclosure, /Applied search filters/);
  assert.doesNotMatch(html, /At a glance/, "do not duplicate expanded ICP outside the disclosure");
  const filtersStart = html.indexOf("Applied search filters");
  const filters = html.slice(filtersStart, html.indexOf("</section>", filtersStart));
  assert.match(filters, /industry<\/dt><dd[^>]*>SaaS/);
  assert.match(filters, /location<\/dt><dd[^>]*>United States/);
  assert.doesNotMatch(filters, /Small businesses|not a filter|keywords|title/);
  assert.match(html, /not additional hard filters/);
});

test("legacy research with an empty plan explains missing ICP instead of inventing one", async () => {
  const components = await loadModule("../components/dashboard/DiscoveryDetailWorkspace.tsx", { react: React });
  const html = renderToStaticMarkup(React.createElement(components.DiscoveryResearchBriefing, {
    view: { query: "Old search", narrativeTitle: "Research complete", narrativeLines: [], companyCount: 0,
      plan: { icpSummary: "", industries: [], geography: [] }, metadata: { ui_filters: "malformed" } }, resultCount: 0,
  }));
  assert.match(html, /No interpreted ICP was saved for this search/);
  assert.match(html, /No additional search filters were recorded/);
  assert.doesNotMatch(html, /SaaS|Founder/);
});

test("unconfirmed Discovery capabilities cannot silently submit a literal lead-list search", async () => {
  const page = await readFile(new URL("../app/(dashboard)/discovery/page.tsx", import.meta.url), "utf8");
  const fallback = page.slice(page.indexOf("if (!providerSearchEnabled)"), page.indexOf("setStartingSearch(true)"));
  assert.match(fallback, /Search capabilities could not be confirmed/);
  assert.doesNotMatch(fallback, /writeState|listWorkspaceLeads|startDiscoverySearch/);
  assert.match(page, /Loading saved leads timed out\. This does not mean the search failed/);
  assert.match(page, /The search may already be running; check Search history/);
});
