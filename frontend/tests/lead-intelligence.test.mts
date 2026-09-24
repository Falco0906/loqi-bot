import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const page = await readFile(new URL("../app/(dashboard)/lead-intelligence/page.tsx", import.meta.url), "utf8");

test("Lead Intelligence waits for an explicit analysis action", () => {
  assert.match(page, /const analyze = async/);
  assert.match(page, /onClick=\{\(\) => void analyze\(\)\}/);
  assert.doesNotMatch(page, /useEffect/);
});

test("Lead Intelligence renders distinct fact, signal, assessment, and guidance sections", () => {
  for (const heading of ["Business guidance", "Derived assessment", "Facts", "Observed signals", "Recommended approach"]) {
    assert.ok(page.includes(heading), `missing ${heading}`);
  }
  assert.match(page, /analysis\.business_guidance\.note/);
});

test("Lead Intelligence presents a processing state and never offers sending", () => {
  assert.match(page, /Analyzing selected leads/);
  assert.doesNotMatch(page, /Send Now|Gmail|generate_outreach_email|campaign launch/);
});

test("Lead Intelligence makes AI drafting an explicit, review-only action", () => {
  assert.match(page, /analysis && <button/);
  assert.match(page, /Generate strategy & draft/);
  assert.match(page, /AI-generated strategy and outreach draft/);
  assert.match(page, /Copy draft/);
  assert.doesNotMatch(page, /useEffect/);
});

test("Lead Intelligence reports copy success or a safe manual-copy fallback", () => {
  assert.match(page, /navigator\.clipboard\.writeText/);
  assert.match(page, /Draft copied to clipboard/);
  assert.match(page, /Select and copy the text manually/);
});
