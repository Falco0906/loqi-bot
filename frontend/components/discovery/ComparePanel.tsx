"use client";

import type { Lead } from "../../lib/types";
import Icon from "../shared/Icon";

type Props = {
  leads: Lead[];
  onClose: () => void;
};

function deriveSignals(lead: Lead): string[] {
  const signals: string[] = [];
  const bs = lead.buying_signals || [];
  const re = lead.recent_events || [];
  const tech = lead.company_technology || {};
  const st = [...bs, ...re].map((s) => s.toLowerCase());

  if (st.some((s) => s.includes("hire") || s.includes("recruit"))) signals.push("Hiring");
  if (st.some((s) => s.includes("fund") || s.includes("series") || s.includes("raise"))) signals.push("Funding");
  if (st.some((s) => s.includes("location") || s.includes("branch") || s.includes("new office"))) signals.push("Expanding");
  if (lead.company_growth_stage?.toLowerCase().includes("growth")) signals.push("Growing");
  const techKeys = Object.keys(tech).map((k) => k.toLowerCase());
  if (techKeys.some((k) => k.includes("hubspot"))) signals.push("Uses HubSpot");
  if (techKeys.some((k) => k.includes("salesforce"))) signals.push("Uses Salesforce");
  if ((lead.buying_authority ?? 0) >= 70) signals.push("Decision Maker");
  if (signals.length === 0) signals.push("Active");
  return signals.slice(0, 3);
}

function getPrimarySignal(lead: Lead): string {
  const signals = deriveSignals(lead);
  return signals[0] || "Active";
}

function getBuyingSignals(lead: Lead): string[] {
  return (lead.buying_signals || []).slice(0, 2);
}

function getRecentEvents(lead: Lead): string[] {
  return (lead.recent_events || []).slice(0, 2);
}

export default function ComparePanel({ leads, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface-lowest border border-outline-variant/10 rounded-2xl w-[90vw] max-w-6xl max-h-[85vh] overflow-hidden flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/10">
          <h2 className="text-headline-md font-bold text-on-surface">
            Compare {leads.length} {leads.length === 1 ? "Company" : "Companies"}
          </h2>
          <button onClick={onClose} className="text-on-surface-variant/60 hover:text-on-surface transition-colors">
            <Icon name="close" />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-6 py-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-label-md text-on-surface-variant uppercase tracking-wider">
                <th className="pb-3 pr-4 w-48">Company</th>
                {leads.map((lead, i) => (
                  <th key={i} className="pb-3 px-3 min-w-[180px]">
                    <div className="flex flex-col">
                      <span className="font-bold text-on-surface">
                        {lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Unknown"}
                      </span>
                      <span className="text-on-surface-variant/70 text-xs font-normal">
                        {lead.company || ""}
                      </span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5">
              <Row label="Role" cells={leads.map((l) => l.title || "—")} />
              <Row label="Primary Signal" cells={leads.map((l) => (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs">
                  {getPrimarySignal(l)}
                </span>
              ))} />
              <Row label="Why Loqi picked them" cells={leads.map((l) => {
                const reasons = l.commercial_score_breakdown?.highlights || [];
                return reasons.length > 0 ? reasons[0] : (l.company_description || "").slice(0, 100) || "—";
              })} />
              <Row label="Growth Signals" cells={leads.map((l) => {
                const growth = deriveSignals(l);
                return growth.length > 0 ? growth.join(", ") : "—";
              })} />
              <Row label="Buying Signals" cells={leads.map((l) => {
                const b = getBuyingSignals(l);
                return b.length > 0 ? b.join(", ") : "—";
              })} />
              <Row label="Messaging Angle" cells={leads.map((l) => {
                const highlights = l.commercial_score_breakdown?.highlights || [];
                return highlights.length > 0 ? highlights[0] : "Standard outreach";
              })} />
              <Row label="Recent Events" cells={leads.map((l) => {
                const ev = getRecentEvents(l);
                return ev.length > 0 ? ev.join("; ") : "—";
              })} />
            </tbody>
          </table>
        </div>

        <div className="px-6 py-3 border-t border-outline-variant/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 bg-primary text-on-primary font-bold rounded-lg hover:brightness-110 transition-all text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, cells }: { label: string; cells: React.ReactNode[] }) {
  return (
    <tr>
      <td className="py-3 pr-4 font-medium text-on-surface-variant whitespace-nowrap">{label}</td>
      {cells.map((cell, i) => (
        <td key={i} className="py-3 px-3 text-on-surface">{cell}</td>
      ))}
    </tr>
  );
}
