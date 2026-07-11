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

export type Lead = {
  lead_id?: string;
  id?: string;
  name?: string;
  first_name?: string;
  last_name?: string;
  title?: string;
  company?: string;
  email?: string;
  linkedin_url?: string;
  buying_authority?: number;
  department?: string;
  company_industry?: string;
  company_description?: string;
  pain_points?: string[];
  buying_signals?: string[];
  commercial_score?: number;
  commercial_score_breakdown?: {
    buyer_score?: number;
    company_score?: number;
    authority_score?: number;
    relevance_score?: number;
    final_score?: number;
    highlights?: string[];
    excluded?: boolean;
    excluded_reason?: string;
  };
  company_growth_stage?: string;
  company_technology?: Record<string, unknown>;
  company_revenue_band?: string;
  company_employees?: number;
  company_locations?: number;
  company_founded?: number;
  recent_events?: string[];
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
