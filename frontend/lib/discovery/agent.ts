import { ResearchContext } from "./context";
import { ResearchEvent } from "./types";

export interface ResearchAgent {
  id: string;
  execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void>;
  cancel(): void;
}
