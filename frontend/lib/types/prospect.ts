export interface Prospect {
  id: string;
  lead_id?: string;
  company: string;
  contact: string;
  title: string;
  location: string;
  summary: string;
  confidence: number;
  avatar?: string;
  metadata?: Record<string, unknown>;
  buying_signals?: string[];
  name?: string;
  // Fallback for legacy compatibility
  [key: string]: unknown;
}
