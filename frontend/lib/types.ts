export type LoqiMessage = {
  id: string;
  role: "user" | "assistant";
  type: string;
  text: string;
  data?: Record<string, unknown>;
  created_at?: string;
};

export type LoqiSessionSummary = {
  ok: boolean;
  session_token: string;
  user_id: string;
  display_name?: string;
  gmail_connected: boolean;
  workflow_sessions: Array<{
    id: string;
    title?: string;
    updated_at?: string;
  }>;
  messages: LoqiMessage[];
};

export type LeadIntelligence = {
  fit_score: number;
  confidence: number;
  why_selected: string[];
  recommended_pitch: string;
  decision_authority_summary: string;
  buying_stage: string;
  urgency: string;
  estimated_business_need: string;
  objection_risk: string;
  best_contact_reason: string;
  summary: string;
};
