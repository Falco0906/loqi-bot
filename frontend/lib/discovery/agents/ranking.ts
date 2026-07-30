import { ResearchAgent } from "../agent";
import { ResearchContext } from "../context";
import { ResearchEvent } from "../types";
import { Prospect } from "../../types/prospect";

export class RankingAgent implements ResearchAgent {
  id = "ranking";
  async execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void> {
    onEvent({ type: "RANKING_PROSPECTS" });
    ctx.phase = "ranking";
    ctx.results = ctx.companies.map(c => {
      let score = 0;
      const reasons: string[] = [];
      if (ctx.parsedQuery?.industry && c.industry.toLowerCase().includes(ctx.parsedQuery.industry.toLowerCase())) { score += 50; reasons.push("Industry match"); }
      if (c.hiring) { score += 30; reasons.push("Currently hiring"); }
      
      return {
        id: c.id,
        company: c.name,
        contact: "Placeholder Contact",
        title: "Key Decision Maker",
        location: c.location,
        summary: `Matched because: ${reasons.join(", ")}.`,
        confidence: score
      } as Prospect;
    }).sort((a, b) => b.confidence - a.confidence);
  }
  cancel() {}
}
