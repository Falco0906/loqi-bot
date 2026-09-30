import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const onboarding = await readFile(new URL("../app/onboarding/page.tsx", import.meta.url), "utf8");
const dashboardLayout = await readFile(new URL("../app/(dashboard)/layout.tsx", import.meta.url), "utf8");

test("Beta onboarding makes Gmail optional while retaining the existing OAuth action", () => {
  assert.match(onboarding, /Continue without Gmail/);
  assert.match(onboarding, /const handleSkipConnection = async/);
  assert.match(onboarding, /onboarding_step: "executive-briefing"/);
  assert.match(onboarding, /onSkip=\{handleSkipConnection\}/);
  assert.match(onboarding, /onClick=\{onConnect\}/);
  assert.match(onboarding, /Connect Account/);
  assert.doesNotMatch(onboarding, /need access to your Google Workspace/);
});

test("Workspace access remains gated by authentication and onboarding completion, not Gmail", () => {
  assert.match(dashboardLayout, /onboarding_complete/);
  assert.doesNotMatch(dashboardLayout, /gmail_connected/);
});
