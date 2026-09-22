/**
 * Read-only confirmation for a campaign-lead POST whose HTTP response was
 * lost. Campaign data is canonical: the client must never retry the mutation
 * merely because its own request deadline elapsed.
 */
export function campaignContainsLeadIds(
  campaign: Record<string, unknown>,
  leadIds: Iterable<string>,
): boolean {
  const canonicalIds = new Set(
    Array.isArray(campaign.leads)
      ? campaign.leads
          .filter((lead): lead is Record<string, unknown> => Boolean(lead) && typeof lead === "object")
          .map((lead) => String(lead.id || ""))
          .filter(Boolean)
      : [],
  );

  for (const leadId of leadIds) {
    if (!canonicalIds.has(leadId)) return false;
  }
  return true;
}

export function campaignHasAttachedDiscovery(
  campaign: Record<string, unknown>,
  discoveryId: string,
): boolean {
  return String(campaign.discovery_id || "") === discoveryId;
}
