export type OutreachChannel = "email" | "linkedin" | "twitter";
export type OutreachStrategyType = "hiring" | "growth" | "technology" | "product_launch";

export interface OutreachStrategy {
  channel: OutreachChannel;
  type: OutreachStrategyType;
  angle: string;
  valueProposition: string;
  confidence: number;
}

export interface OutreachDraft {
  subject: string;
  opening: string;
  body: string;
  cta: string;
  closing: string;
  reasoning: string;
}

export interface OutreachContext {
  strategy: OutreachStrategy;
  draft: OutreachDraft;
  warnings: string[];
  suggestions: string[];
}
