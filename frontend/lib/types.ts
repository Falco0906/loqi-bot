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
