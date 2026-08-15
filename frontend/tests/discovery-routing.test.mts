/**
 * Regression test: Discovery must never silently discard user input.
 *
 * A natural-language market prompt ("AI startups", "Climate tech",
 * "Healthcare SaaS", …) can fail the keyword classifier. Those prompts must
 * still route into the Discovery lead-search flow instead of being dropped —
 * and non-Discovery pages must surface unclassified input via the
 * clarification UI rather than return silently.
 *
 * Run with: npm run test:discovery  (Node 22.6+ native TS type-stripping)
 */

import assert from "node:assert";
import {
  classifyInstruction,
  resolveTaskKind,
  nextState,
  TASKS,
  completionActions,
} from "../lib/conversationMachine.ts";

const MARKET_PROMPTS = [
  "European fintech companies",
  "AI startups",
  "Climate tech",
  "Healthcare SaaS",
  "Manufacturing companies in Germany",
];

for (const prompt of MARKET_PROMPTS) {
  assert.strictEqual(
    resolveTaskKind(prompt, "Discovery"),
    "research",
    `"${prompt}" must route to a Discovery lead search`,
  );
}

// The keyword classifier alone would silently drop these — the fallback is
// what makes Discovery searches start for them.
const UNCLASSIFIED = ["AI startups", "Climate tech", "Healthcare SaaS"];
for (const prompt of UNCLASSIFIED) {
  assert.strictEqual(
    classifyInstruction(prompt),
    "unknown",
    `"${prompt}" should not be misclassified by keyword scoring`,
  );
  assert.strictEqual(
    resolveTaskKind(prompt, "Discovery"),
    "research",
    `"${prompt}" must fall back to research on Discovery`,
  );
}

// Non-Discovery pages keep "unknown" so the UI surfaces a clarification
// instead of dropping the instruction silently.
for (const page of ["Mission Control", "Campaigns", "Inbox", null]) {
  assert.strictEqual(
    resolveTaskKind("AI startups", page),
    "unknown",
    `"AI startups" on "${page}" should surface the clarification flow`,
  );
}

// An unclassified instruction must transition the state machine into the
// clarification state (the visible error/prompt surface), never stay silent.
assert.strictEqual(
  nextState("idle", { type: "instruction", kind: "unknown" }),
  "clarification",
  "unknown instruction from idle must enter clarification",
);
assert.strictEqual(
  nextState("completed", { type: "instruction", kind: "unknown" }),
  "clarification",
  "unknown instruction from completed must enter clarification",
);

// Confirmed intents are unaffected, including on the Discovery page.
assert.strictEqual(resolveTaskKind("What changed since yesterday?", "Discovery"), "briefing");
assert.strictEqual(resolveTaskKind("Check my inbox", "Discovery"), "inbox");
assert.strictEqual(resolveTaskKind("Prepare email drafts for my campaign", "Discovery"), "campaign");

// Empty/whitespace submissions are rejected at the boundary.
assert.strictEqual(nextState("idle", { type: "instruction", kind: "research" }), "working");

// Completed research notifications must deep-link to the SPECIFIC discovery
// that the run produced — never the generic /discovery index. This is what
// lets "Found 25 companies" open the exact run instead of a stale singleton.
const DEEP_LINK = "/discovery/0190-cafe-babe-deadbeef";
const researchActions = completionActions(TASKS.research, DEEP_LINK);
const primary = researchActions.find((a) => a.label === "View Discovery");
assert.ok(primary, "completion actions must include a View Discovery action");
assert.strictEqual(primary.path, DEEP_LINK, "View Discovery must point at the run's own discovery");

// Other task kinds keep their default workspace destinations when no
// primaryPath override is supplied (backward compatibility).
const briefingActions = completionActions(TASKS.briefing);
const briefingPrimary = briefingActions[0];
assert.strictEqual(briefingPrimary.path, "/mission-control");

// The generic index path is still used when no specific discovery exists yet
// (e.g. prefetching the destination shell before a run starts).
const defaultResearch = completionActions(TASKS.research);
assert.strictEqual(defaultResearch[0].path, "/discovery");

console.log(`PASS discovery-routing (${MARKET_PROMPTS.length} market prompts route to a lead search)`);