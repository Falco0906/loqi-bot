export type CopilotResourceContextLike = {
  discoveryId?: string;
  selectedLeadIds?: string[];
  campaignId?: string;
  draftId?: string;
  conversationId?: string;
  knowledge?: { category?: string; itemId?: string; query?: string };
  analytics?: { scope?: string; campaignId?: string; campaignIds?: string[] };
};

/** Flatten persisted resource context into the backend's existing page context shape. */
export function mergeCopilotResourceContext(
  pageData: Record<string, unknown> | undefined,
  resource: CopilotResourceContextLike | null | undefined,
): Record<string, unknown> {
  const pageSelected = pageData?.selected_lead_ids;
  const hasPageSelection = Array.isArray(pageSelected) && pageSelected.length > 0;
  const copilotSelected = resource?.selectedLeadIds;
  const hasCopilotSelection = Array.isArray(copilotSelected) && copilotSelected.length > 0;
  return {
    ...(pageData || {}),
    discovery_id: pageData?.discovery_id || resource?.discoveryId,
    // A ranked/filter result is the referent for the next Copilot turn. The
    // page's broader table selection must not replace it.
    selected_lead_ids: hasCopilotSelection ? copilotSelected : (hasPageSelection ? pageSelected : undefined),
    campaign_id: pageData?.campaign_id || resource?.campaignId,
    draft_id: pageData?.draft_id || resource?.draftId,
    conversation_id: pageData?.conversation_id || resource?.conversationId,
    knowledge: pageData?.knowledge || resource?.knowledge,
    analytics: pageData?.analytics || resource?.analytics,
  };
}

/** Capability results are authoritative only when attached to their tool namespace. */
export function extractCopilotCapabilityResult(tool: unknown, result: unknown): unknown | undefined {
  if (typeof tool !== "string" || !result || typeof result !== "object") return undefined;
  return /^(lead|campaign|outreach|inbox|knowledge|analytics)\./.test(tool) ? result : undefined;
}

export function resultMatchesResource(
  result: Record<string, unknown> | null | undefined,
  resourceId: string,
  keys: string[],
): boolean {
  if (!result || !resourceId) return false;
  return keys.some((key) => String(result[key] || "") === resourceId);
}

/** Carry the authoritative lead ordering/selection into the next Copilot turn. */
export function leadIdsFromResult(result: { leads?: Array<Record<string, unknown>> } | null | undefined): string[] {
  return (result?.leads || [])
    .map((lead) => String(lead.id || "").trim())
    .filter(Boolean);
}
