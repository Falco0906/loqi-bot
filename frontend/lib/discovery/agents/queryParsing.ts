import { ResearchAgent } from "../agent";
import { ResearchContext } from "../context";
import { ResearchEvent } from "../types";

export class QueryParsingAgent implements ResearchAgent {
  id = "query-parsing";
  async execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void> {
    onEvent({ type: "UNDERSTANDING_REQUEST" });
    ctx.phase = "parsing";
    ctx.parsedQuery = {
      keywords: ctx.query.toLowerCase().split(" "),
      exclusions: [],
      industry: ctx.query.toLowerCase().includes("saas") ? "SaaS" : undefined,
    };
  }
  cancel() {}
}
