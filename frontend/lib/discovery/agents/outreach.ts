import { ResearchAgent } from "../agent";
import { ResearchContext } from "../context";
import { ResearchEvent } from "../types";

export class OutreachAgent implements ResearchAgent {
  id = "outreach";
  
  async execute(ctx: ResearchContext, onEvent: (event: ResearchEvent) => void): Promise<void> {
    if (ctx.results.length === 0) return;
    
    onEvent({ type: "PREPARING_RECOMMENDATIONS" }); // Reuse existing event, or extend? I'll use existing.
    ctx.phase = "outreach";
    
    const topProspect = ctx.results[0];
    
    ctx.outreachContext = {
      strategy: {
        channel: "email",
        type: "growth",
        angle: "Pain point focused",
        valueProposition: "Automated AI research",
        confidence: 0.9,
      },
      draft: {
        subject: `Quick question about ${topProspect.company}`,
        opening: `Hi ${topProspect.contact.split(" ")[0]},`,
        body: `I noticed ${topProspect.company} is ${topProspect.summary.toLowerCase()}. We help teams like yours streamline this process.`,
        cta: "Do you have 5 minutes to chat?",
        closing: "Best, [My Name]",
        reasoning: "Matched because company is hiring and in high-growth SaaS."
      },
      warnings: [],
      suggestions: ["Personalize the opening with a specific recent news item."]
    };
  }

  cancel() {}
}
