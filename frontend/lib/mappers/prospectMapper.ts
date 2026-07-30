import { Lead } from "../types";
import { Prospect } from "../types/prospect";

export function mapLeadToProspect(lead: Lead): Prospect {
  return {
    id: lead.lead_id || lead.id || Math.random().toString(),
    company: lead.company || "Unknown Company",
    contact: lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Unknown Contact",
    title: lead.title || "No Title",
    location: "Unknown", // lead.location not available
    summary: lead.company_description || lead.pain_points?.[0] || "No summary available.",
    confidence: lead.commercial_score || 0,
    avatar: undefined, // lead.avatar_url not available
    metadata: {
      buying_signals: lead.buying_signals || [],
    },
    buying_signals: lead.buying_signals || [],
  };
}
