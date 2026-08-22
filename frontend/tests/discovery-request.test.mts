/**
 * PR-4.5 — Discovery request normalization regressions.
 *
 * Both entry points (Discovery search box + Copilot) must converge on the
 * same canonical target. Filler must never contaminate the search.
 *
 * Run: node tests/discovery-request.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";

const { normalizeDiscoveryRequest } = await import("../lib/discovery-request.ts");

test("M1. 'find me venture capitalists' → 'venture capitalists'", () => {
  const r = normalizeDiscoveryRequest("find me venture capitalists");
  assert.equal(r.target, "venture capitalists");
  assert.equal(r.limit, null);
  assert.ok(!r.target.includes("me "), `pronoun residue: ${r.target}`);
});

test("M2. 'I need more leads on VCs' → VCs preserved", () => {
  const r = normalizeDiscoveryRequest("I need more leads on VCs");
  assert.equal(r.limit, null);
  // "on" is a constraint preposition — keep the whole tail as target.
  assert.match(r.target, /vcs/i);
  assert.ok(!/^i need/i.test(r.target), "filler must be stripped");
});

test("M3. 'find AI startup founders in India' keeps constraints", () => {
  const r = normalizeDiscoveryRequest("find AI startup founders in India");
  assert.match(r.target, /ai startup founders in india/i);
  assert.equal(r.limit, null);
});

test("M4. 'show me SaaS companies in the US' keeps geography", () => {
  const r = normalizeDiscoveryRequest("show me SaaS companies in the US");
  assert.match(r.target, /saas.*us|saas.*u s/i);
});

test("M5. count extraction: 'find me 50 fintech founders'", () => {
  const r = normalizeDiscoveryRequest("find me 50 fintech founders");
  assert.equal(r.limit, 50);
  assert.match(r.cleanedQuery, /50/);
});

test("M6. bare target passes through unchanged", () => {
  const r = normalizeDiscoveryRequest("venture capitalists");
  assert.equal(r.target, "venture capitalists");
});

test("M7. filler-only input degrades to empty target (caller clarifies)", () => {
  const r = normalizeDiscoveryRequest("help me");
  assert.equal(r.target, "");
});

test("M8. trailing 'for me' stripped", () => {
  const r = normalizeDiscoveryRequest("source leads for me");
  assert.equal(r.target, "leads");
});


// ── PR-4.5F: expanded spec examples ──────────────────────────────────────

test("X1. 'find me VCs' → 'VCs' (VC never stripped)", () => {
  const r = normalizeDiscoveryRequest("find me VCs");
  assert.match(r.target, /vcs/i);
});

test("X2. 'I need venture capitalists' → 'venture capitalists'", () => {
  assert.equal(normalizeDiscoveryRequest("I need venture capitalists").target,
               "venture capitalists");
});

test("X3. geography preserved: 'get me SaaS founders in India'", () => {
  const r = normalizeDiscoveryRequest("get me SaaS founders in India");
  assert.match(r.target, /india/i);
  assert.ok(!/^me /.test(r.target));
});

test("X4. geography preserved: US never treated as pronoun", () => {
  const r = normalizeDiscoveryRequest("show me SaaS companies in the US");
  assert.match(r.target, /us/i);
});

test("X5. B2B SaaS preserved: 'find me 50 B2B SaaS companies'", () => {
  const r = normalizeDiscoveryRequest("find me 50 B2B SaaS companies");
  assert.equal(r.limit, 50);
  assert.match(r.target.replace(/\b50\b/, ""), /b2b saas/i);
});

test("X6. 'research AI startups in India' → target keeps AI + India", () => {
  const r = normalizeDiscoveryRequest("research AI startups in India");
  assert.match(r.target, /ai startups in india/i);
});

test("X7. 'find 25 fintech startups in the US' → limit + geo", () => {
  const r = normalizeDiscoveryRequest("find 25 fintech startups in the US");
  assert.equal(r.limit, 25);
  assert.match(r.target, /fintech startups/i);
  assert.match(r.target, /us/i);
});
