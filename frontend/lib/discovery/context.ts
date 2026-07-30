import { Prospect } from "../types/prospect";
import { ParsedQuery, Company } from "../types/discoveryModels";
import { OutreachContext } from "../types/outreach";

export interface ResearchContext {
  query: string;
  parsedQuery?: ParsedQuery;
  companies: Company[];
  phase: "idle" | "parsing" | "searching" | "ranking" | "recommending" | "outreach";
  results: Prospect[];
  recommendations: string[];
  outreachContext?: OutreachContext;
  error: string | null;
}
