import { ResearchOrchestrator } from "../orchestrator";
import { ResearchEvent } from "../types";
import { ResearchContext } from "../context";
import { ResearchAgent } from "../agent";
import { QueryParsingAgent } from "../agents/queryParsing";
import { CompanySearchAgent } from "../agents/companySearch";
import { RankingAgent } from "../agents/ranking";
import { RecommendationAgent } from "../agents/recommendation";
import { OutreachAgent } from "../agents/outreach";

export class ResearchAgentPipeline implements ResearchOrchestrator {
  private agents: ResearchAgent[] = [
    new QueryParsingAgent(),
    new CompanySearchAgent(),
    new RankingAgent(),
    new RecommendationAgent(),
    new OutreachAgent(),
  ];
  private abortController: AbortController | null = null;

  async startResearch(query: string, onEvent: (event: ResearchEvent) => void): Promise<void> {
    this.abortController = new AbortController();
    const context: ResearchContext = {
      query,
      companies: [],
      phase: "idle",
      results: [],
      recommendations: [],
      error: null
    };

    try {
      onEvent({ type: "STARTED" });
      
      for (const agent of this.agents) {
        if (this.abortController.signal.aborted) throw new Error("Cancelled");
        await agent.execute(context, onEvent);
      }
      
      onEvent({ type: "COMPLETED", results: context.results });
    } catch (err) {
      if (err instanceof Error && err.message === "Cancelled") {
        onEvent({ type: "ERROR", error: { type: "Cancelled", message: "Search cancelled" } });
      } else {
        onEvent({ type: "ERROR", error: { type: "Unknown", message: "Pipeline failed" } });
      }
    }
  }

  cancelResearch(): void {
    this.abortController?.abort();
    this.agents.forEach(a => a.cancel());
  }
}
