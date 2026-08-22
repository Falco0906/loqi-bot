"use client";

/**
 * PR-4.5 — Canonical Copilot action layer.
 *
 * The ONLY place where the Copilot (sidebar or full page) turns an intent
 * into application operations. Direct user actions and Copilot actions MUST
 * converge here — no duplicate implementations.
 *
 * Each action:
 *   - normalizes input deterministically (discovery-request.ts)
 *   - invokes the SAME canonical operation the destination page uses
 *   - returns identifiers so callers can navigate/report
 *   - never swallows auth/ownership errors into fake success.
 */

import { normalizeDiscoveryRequest } from "./discovery-request";
import { startDiscoverySearch } from "./repositories";

export type DiscoveryAction = {
  kind: "search_discovery";
  discoveryId: string;
  jobId: string;
  /** Deterministic normalized target (debuggable, logged). */
  target: string;
  limit: number | null;
  cleanedQuery: string;
};

export type CopilotActionResult =
  | { ok: true; action: DiscoveryAction }
  | { ok: false; errorCategory: "auth" | "invalid" | "provider" | "unknown"; message: string };

export type ActionSurface = "sidebar" | "copilot-page" | "discovery";

/**
 * CANONICAL DISCOVERY SEARCH OPERATION.
 *
 * Used by:
 *   - Discovery page search box (direct user action)
 *   - Copilot sidebar ("I need more leads on VCs")
 *   - Full Copilot page
 *
 * All three converge on startDiscoverySearch → POST /api/discoveries → the
 * Phase-4 durable job pipeline. Normalization guarantees the same natural
 * language produces the same target regardless of surface.
 */
export async function searchDiscoveryAction(
  sessionToken: string,
  rawInput: string,
  surface: ActionSurface,
): Promise<DiscoveryAction | null> {
  const normalized = normalizeDiscoveryRequest(rawInput);
  const query = normalized.cleanedQuery || rawInput.trim();

  // Structured observability — identifiers only, no secrets.
  console.info(
    `[copilot-action] search_discovery surface=${surface} ` +
    `target="${normalized.target.slice(0, 80)}" limit=${normalized.limit ?? "-"}`
  );

  const started = await startDiscoverySearch(query);
  if (!started) {
    return null; // caller surfaces actionable failure (auth/session)
  }

  return {
    kind: "search_discovery",
    discoveryId: started.discoveryId,
    jobId: started.jobId,
    target: normalized.target || rawInput.trim(),
    limit: normalized.limit,
    cleanedQuery: query,
  };
}
