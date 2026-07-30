import { ResearchOrchestrator } from "./orchestrator";
import { ResearchEvent } from "./types";
import { Prospect } from "../types/prospect";

export class MockResearchOrchestrator implements ResearchOrchestrator {
  private abortController: AbortController | null = null;

  async startResearch(query: string, onEvent: (event: ResearchEvent) => void): Promise<void> {
    this.abortController = new AbortController();
    
    try {
      onEvent({ type: "STARTED" });
      
      const simulateStep = async (event: ResearchEvent, delay: number) => {
        if (this.abortController?.signal.aborted) throw new Error("Cancelled");
        await new Promise(resolve => setTimeout(resolve, delay));
        onEvent(event);
      };

      await simulateStep({ type: "UNDERSTANDING_REQUEST" }, 500);
      await simulateStep({ type: "FINDING_COMPANIES" }, 800);
      await simulateStep({ type: "RANKING_PROSPECTS" }, 800);
      await simulateStep({ type: "PREPARING_RECOMMENDATIONS" }, 800);
      
      onEvent({ type: "COMPLETED", results: [] });
    } catch (err) {
      if (err instanceof Error && err.message === "Cancelled") {
        onEvent({ type: "ERROR", error: { type: "Cancelled", message: "Search cancelled" } });
      } else {
        onEvent({ type: "ERROR", error: { type: "Unknown", message: "Failed to research" } });
      }
    }
  }

  cancelResearch(): void {
    this.abortController?.abort();
  }
}
