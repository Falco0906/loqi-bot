import { Prospect } from "../types/prospect";
import { OutreachContext } from "../types/outreach";

export type SearchPhase = "idle" | "submitting" | "processing" | "completed" | "error";
export type ResearchErrorType = "RateLimited" | "Cancelled" | "NetworkFailure" | "ProviderUnavailable" | "Unknown";

export interface ResearchError {
  type: ResearchErrorType;
  message: string;
}

export type ResearchEvent = 
  | { type: "STARTED" }
  | { type: "UNDERSTANDING_REQUEST" }
  | { type: "FINDING_COMPANIES" }
  | { type: "RANKING_PROSPECTS" }
  | { type: "PREPARING_RECOMMENDATIONS" }
  | { type: "COMPLETED"; results: Prospect[]; outreachContext?: OutreachContext }
  | { type: "ERROR"; error: ResearchError };
