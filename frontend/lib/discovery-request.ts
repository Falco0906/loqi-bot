/**
 * PR-4.5 — deterministic Discovery request normalization.
 *
 * Both entry points (Discovery search box and Copilot) must converge on the
 * same canonical search target. This module is PURE — no network, no LLM —
 * so direct searches stay instant and behavior is inspectable/testable.
 *
 * Contract:
 *   normalizeDiscoveryRequest("Find me venture capitalists")
 *     → { target: "venture capitalists", limit: null, cleanedQuery: "venture capitalists" }
 *
 * Handles: leading filler phrases ("find me", "i need", "show me",
 * "get me", "i'm looking for", "search for", "research", …), pronoun
 * residue ("me"), lead-nouns ("leads", "prospects", "companies" as the
 * OBJECT of the sentence are stripped only when more specific words exist),
 * and count extraction ("find me 50 fintech founders" → limit 50).
 */

const FILLER_PATTERNS: RegExp[] = [
  /^\s*(?:please\s+)?(?:can|could|would)\s+you\s+/i,
  /^\s*(?:i\s*'|i\s+am\s+)?looking\s+for\s+(?:me\s+)?/i,
  /^\s*(?:find|get|show|bring|give)\s+me\s+/i,
  /^\s*(?:i\s+need|i\s+want|need)\s+(?:more\s+)?(?=[a-z])/i,
  /^\s*(?:find|get|show|source|discover|research|pull)\s+(?:more\s+)?/i,
  /^\s*(?:help\s+me\s+)(?:find|get|source|discover)?\s*/i,
  /^\s*help\s+me\s*/i,
  /^\s*(?:what|which)\b/i,
  /^\s*(?:run|start|create)\s+(?:a\s+)?(?:new\s+)?discovery\s+(?:for|on|into)\s+/i,
];

const TRAILING_FILLER = /\s+(?:for\s+me|please)$/i;

// Nouns that describe WHAT Loqi returns rather than WHO to target. Stripped
// only when something meaningful remains (never strips down to nothing).
const RESULT_NOUNS = new Set([
  "leads", "lead", "prospects", "prospect", "companies", "company",
  "contacts", "contact", "people", "founders?", "", // "" guards double spaces
]);

// Only unambiguous pronouns. NEVER include "us"/"in" — they collide with
// geography ("US") and constraint prepositions ("in India").
const STOP_PRONOUNS = new Set(["me", "my", "i", "our"]);

export type NormalizedDiscoveryRequest = {
  /** Clean search target, e.g. "venture capitalists in india". */
  target: string;
  /** Explicit count if the user asked for one (e.g. "50 fintech founders"). */
  limit: number | null;
  /** Canonical query to send to the Discovery pipeline. */
  cleanedQuery: string;
};

export function normalizeDiscoveryRequest(input: string): NormalizedDiscoveryRequest {
  let t = (input ?? "").trim();

  // Repeatedly peel leading filler ("I need to find me…" etc).
  let changed = true;
  while (changed && t) {
    changed = false;
    for (const pattern of FILLER_PATTERNS) {
      const next = t.replace(pattern, "");
      if (next !== t) {
        t = next.trim();
        changed = true;
      }
    }
    t = t.replace(TRAILING_FILLER, "").trim();
  }

  // Extract explicit count ("50 fintech founders").
  let limit: number | null = null;
  const countMatch = t.match(/\b(\d{1,4})\s*\+?\s+\w+/);
  if (countMatch) {
    const n = parseInt(countMatch[1], 10);
    if (n > 0 && n <= 1000) limit = n;
  }

  // Drop pronoun residue anywhere ("venture me capitalists" → never).
  let words = t.replace(/[^a-z0-9 ]/gi, " ").split(/\s+/).filter(Boolean);

  // Strip a LEADING result noun only when there's a real target after it
  // ("leads for VCs" → keep; bare "leads" → keep, it IS the target).
  if (
    words.length > 2 &&
    RESULT_NOUNS.has(words[0].toLowerCase().replace(/s$/, "")) &&
    !["in", "for", "from", "at", "on"].includes(words[1].toLowerCase())
  ) {
    words = words.slice(1);
  }

  words = words.filter(w => !STOP_PRONOUNS.has(w.toLowerCase()));

  const target = words.join(" ").replace(/\s{2,}/g, " ").trim();
  const cleanedQuery = [target, limit !== null ? `limit ${limit}` : ""]
    .filter(Boolean)
    .join(" ")
    .trim() || input.trim();

  return { target, limit, cleanedQuery };
}
