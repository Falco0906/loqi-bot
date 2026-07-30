import { ResearchAgent } from "../agent";
import { ResearchContext } from "../context";
import { ResearchEvent } from "../types";

export class RecommendationAgent implements ResearchAgent {
  id = "recommendation";
  async execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void> {
    onEvent({ type: "PREPARING_RECOMMENDATIONS" });
    ctx.phase = "recommending";
    if (ctx.results.length === 0) {
      ctx.recommendations = ["Broaden your search criteria.", "Try removing specific industry filters."];
    } else {
      ctx.recommendations = ["Filter by funding stage to prioritize growth.", "Focus on companies with recent hiring activity."];
    }
  }
  cancel() {}
}
