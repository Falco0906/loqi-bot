import { Prospect } from "../types/prospect";
import { ResearchEvent } from "./types";

export interface ResearchOrchestrator {
  startResearch(query: string, onEvent: (event: ResearchEvent) => void): Promise<void>;
  cancelResearch(): void;
  // Future: retryResearch()
}
