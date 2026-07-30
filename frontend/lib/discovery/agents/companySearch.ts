import { ResearchAgent } from "../agent";
import { ResearchContext } from "../context";
import { ResearchEvent } from "../types";
import { MOCK_COMPANY_DATASET } from "../mockDataset";

export class CompanySearchAgent implements ResearchAgent {
  id = "company-search";
  async execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void> {
    onEvent({ type: "FINDING_COMPANIES" });
    ctx.phase = "searching";
    ctx.companies = MOCK_COMPANY_DATASET.filter(company => {
      if (ctx.parsedQuery?.industry && !company.industry.toLowerCase().includes(ctx.parsedQuery.industry.toLowerCase())) return false;
      return true;
    });
  }
  cancel() {}
}
