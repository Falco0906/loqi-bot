import { Prospect } from "../types/prospect";
import { OutreachStrategyType, OutreachContext } from "../types/outreach";

export const generateOutreach = (prospect: Prospect, strategyType: OutreachStrategyType): OutreachContext => {
  const channel = "email";
  let angle = "";
  let body = "";
  let reasoning = "";

  switch (strategyType) {
    case "hiring":
      angle = "Hiring focused";
      body = `I noticed ${prospect.company} is growing the team. We help teams like yours streamline this process.`;
      reasoning = "Matched because company is hiring and in high-growth.";
      break;
    case "growth":
      angle = "Growth focused";
      body = `I've been following ${prospect.company}'s expansion. We help teams accelerate this growth.`;
      reasoning = "Matched because company is showing fast growth.";
      break;
    default:
      angle = "Standard";
      body = `I noticed ${prospect.company}'s work. We help teams like yours.`;
      reasoning = "Standard outreach.";
  }

  return {
    strategy: { channel, type: strategyType, angle, valueProposition: "AI research", confidence: 0.9 },
    draft: {
      subject: `Quick question about ${prospect.company}`,
      opening: `Hi ${prospect.contact.split(" ")[0]},`,
      body,
      cta: "Do you have 5 minutes to chat?",
      closing: "Best, [My Name]",
      reasoning,
    },
    warnings: [],
    suggestions: ["Personalize the opening."]
  };
};
