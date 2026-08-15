/**
 * Campaign ↔ Discovery mode contract.
 *
 * Discovery runs in exactly two explicit modes:
 *   - "standalone":      user-initiated research with no campaign context.
 *   - "campaign_attach": research launched from an existing campaign. The
 *                        campaign context (id, name, objective, audience,
 *                        strategy angle) rides along every navigation in the
 *                        URL so the mode is never inferred from location.
 */
import { startDiscoverySearch } from "./repositories";

export type DiscoveryMode = "standalone" | "campaign_attach";

export const ATTACH_MODE = "campaign_attach" as const;
export const STANDALONE_MODE = "standalone" as const;

export type CampaignAttachContext = {
  campaignId: string;
  campaignName?: string;
  objective?: string;
  audience?: string;
  messagingAngle?: string;
};

export type ParsedDiscoveryMode = {
  mode: DiscoveryMode;
  context: CampaignAttachContext | null;
};

export function buildResearchUrl(ctx: CampaignAttachContext): string {
  const params = new URLSearchParams();
  params.set("mode", ATTACH_MODE);
  params.set("campaign_id", ctx.campaignId);
  if (ctx.campaignName) params.set("campaign_name", ctx.campaignName);
  if (ctx.objective) params.set("objective", ctx.objective);
  if (ctx.audience) params.set("audience", ctx.audience);
  if (ctx.messagingAngle) params.set("messaging_angle", ctx.messagingAngle);
  return `/discovery?${params.toString()}`;
}

export function discoveryDetailUrl(discoveryId: string, ctx: CampaignAttachContext | null): string {
  if (!ctx) return `/discovery/${discoveryId}`;
  const params = new URLSearchParams();
  params.set("mode", ATTACH_MODE);
  params.set("campaign_id", ctx.campaignId);
  if (ctx.campaignName) params.set("campaign_name", ctx.campaignName);
  if (ctx.objective) params.set("objective", ctx.objective);
  if (ctx.audience) params.set("audience", ctx.audience);
  if (ctx.messagingAngle) params.set("messaging_angle", ctx.messagingAngle);
  return `/discovery/${discoveryId}?${params.toString()}`;
}

export function parseDiscoveryMode(
  params: URLSearchParams | null | undefined,
): ParsedDiscoveryMode {
  if (params?.get("mode") === ATTACH_MODE) {
    return {
      mode: ATTACH_MODE,
      context: {
        campaignId: params.get("campaign_id") || "",
        campaignName: params.get("campaign_name") || undefined,
        objective: params.get("objective") || undefined,
        audience: params.get("audience") || undefined,
        messagingAngle: params.get("messaging_angle") || undefined,
      },
    };
  }
  const legacyCampaignId = params?.get("campaign") || "";
  if (legacyCampaignId) {
    return { mode: ATTACH_MODE, context: { campaignId: legacyCampaignId } };
  }
  return { mode: STANDALONE_MODE, context: null };
}

export function buildDiscoveryQuery(ctx: CampaignAttachContext): string {
  const audience = (ctx.audience || "").trim();
  const objective = (ctx.objective || "").trim();
  const angle = (ctx.messagingAngle || "").trim();
  let query = audience ? `${audience} for ${objective}` : objective;
  if (query.length === 0 && angle) query = angle;
  if (query.length > 240) query = query.slice(0, 240);
  return query;
}

export async function startCampaignResearch(
  ctx: CampaignAttachContext,
): Promise<string | null> {
  const query = buildDiscoveryQuery(ctx);
  console.log("[kickoff] startCampaignResearch: enter", { campaignId: ctx.campaignId, query });
  if (!query) {
    console.log("[kickoff] startCampaignResearch: ABORT (empty query)");
    return null;
  }
  const started = await startDiscoverySearch(query);
  console.log("[kickoff] startCampaignResearch: result", started);
  return started ? started.discoveryId : null;
}

export function campaignAttachContext(
  campaign: {
    id?: string;
    name?: string;
    objective?: string;
    strategy?: Record<string, unknown> | null;
  },
): CampaignAttachContext | null {
  if (!campaign?.id) return null;
  const strategy = campaign.strategy;
  const audience =
    typeof strategy === "object" && strategy !== null
      ? String(strategy.audience || "")
      : "";
  const messagingAngle =
    typeof strategy === "object" && strategy !== null
      ? String(strategy.messaging_angle || "")
      : "";
  return {
    campaignId: String(campaign.id),
    campaignName: campaign.name ? String(campaign.name) : undefined,
    objective: campaign.objective ? String(campaign.objective) : undefined,
    audience: audience || undefined,
    messagingAngle: messagingAngle || undefined,
  };
}


