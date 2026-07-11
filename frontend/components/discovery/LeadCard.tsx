"use client";

import type { Lead } from "../../lib/types";
import Icon from "../shared/Icon";

type Signal = {
  label: string;
  variant: "primary" | "secondary" | "tertiary" | "default";
};

function deriveSignals(lead: Lead): Signal[] {
  const signals: Signal[] = [];
  const buyingSignals = lead.buying_signals || [];
  const recentEvents = lead.recent_events || [];
  const tech = lead.company_technology || {};
  const signalText = [...buyingSignals, ...recentEvents].map((s) => s.toLowerCase());

  if (signalText.some((s) => s.includes("hire") || s.includes("recruit") || s.includes("open"))) {
    signals.push({ label: "Recently Hiring", variant: "primary" });
  }
  if (
    lead.company_growth_stage?.toLowerCase().includes("expansion") ||
    lead.company_growth_stage?.toLowerCase().includes("growth") ||
    signalText.some((s) => s.includes("growth") || s.includes("expand"))
  ) {
    signals.push({ label: "Growing Fast", variant: "secondary" });
  }
  if (signalText.some((s) => s.includes("fund") || s.includes("series") || s.includes("raise"))) {
    signals.push({ label: "Funding", variant: "tertiary" });
  }
  if (signalText.some((s) => s.includes("location") || s.includes("branch") || s.includes("new office"))) {
    signals.push({ label: "Opened New Location", variant: "primary" });
  }

  const techKeys = Object.keys(tech).map((k) => k.toLowerCase());
  if (techKeys.some((k) => k.includes("hubspot") || k.includes("hub"))) {
    signals.push({ label: "Uses HubSpot", variant: "default" });
  }
  if (techKeys.some((k) => k.includes("salesforce") || k.includes("sfdc"))) {
    signals.push({ label: "Uses Salesforce", variant: "default" });
  }
  if (techKeys.some((k) => k.includes("outreach") || k.includes("salesloft"))) {
    signals.push({ label: "Uses Outreach", variant: "default" });
  }

  if ((lead.buying_authority ?? 0) >= 70) {
    signals.push({ label: "Decision Maker", variant: "tertiary" });
  }

  if (signals.length === 0) {
    signals.push({ label: "Active", variant: "default" });
  }
  return signals.slice(0, 3);
}

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return null;
  const pct = Math.min(100, Math.max(0, Math.round(score * 100 / 150)));
  const stars = Math.round((pct / 100) * 5);
  return (
    <div className="flex text-tertiary">
      {Array.from({ length: 5 }, (_, i) => (
        <Icon key={i} name="star" className={`text-sm ${i < stars ? "opacity-100" : "opacity-30"}`} fill={i < stars} />
      ))}
    </div>
  );
}

function SignalBadge({ signal }: { signal: Signal }) {
  const variantClasses: Record<string, string> = {
    primary: "bg-primary/10 border-primary/20 text-primary",
    secondary: "bg-secondary/10 border-secondary/20 text-secondary",
    tertiary: "bg-tertiary/10 border-tertiary/20 text-tertiary",
    default: "bg-surface-highest text-on-surface-variant border-outline-variant/10",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-label-md border ${variantClasses[signal.variant]}`}>
      {signal.label}
    </span>
  );
}

type Props = {
  lead: Lead;
  index: number;
  selected: boolean;
  onToggle: (index: number, shiftKey: boolean) => void;
};

export default function LeadCard({ lead, index, selected, onToggle }: Props) {
  const signals = deriveSignals(lead);
  const name = lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Unknown";
  const title = lead.title || "";
  const company = lead.company || "";
  const desc = lead.company_description || lead.pain_points?.[0] || "";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => onToggle(index, e.shiftKey)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(index, e.shiftKey); } }}
      className={`rounded-xl p-4 cursor-pointer transition-all duration-150 select-none active:scale-[0.99] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 animate-slide-up ${
        selected
          ? "border-2 border-primary/60 bg-surface-low shadow-[0_0_0_1px_rgba(139,92,246,0.15)]"
          : "border border-outline-variant/10 bg-surface hover:bg-surface-low hover:border-outline-variant/30"
      }`}
      style={{ animationDelay: `${(index % 10) * 0.03}s` }}
    >
      <div className="flex justify-between items-start mb-3">
        <div className="flex gap-3 items-start">
          <div
            className={`w-5 h-5 rounded border-2 mt-1 flex items-center justify-center shrink-0 transition-colors ${
              selected
                ? "bg-primary border-primary"
                : "border-outline-variant/40 hover:border-primary/50"
            }`}
          >
            {selected ? (
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-on-primary" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z" />
              </svg>
            ) : null}
          </div>
          <div className="w-10 h-10 rounded-lg bg-[#1F1F23] flex items-center justify-center text-on-surface-variant/40 text-xs font-bold shrink-0">
            {name.charAt(0).toUpperCase()}
          </div>
          <div>
            <h3 className="text-body-lg font-bold text-on-surface">{name}</h3>
            <p className="text-on-surface-variant text-body-md">
              {title} {company ? `\u2022 ${company}` : ""}
            </p>
          </div>
        </div>
        <ScoreBadge score={lead.commercial_score} />
      </div>

      <div className="space-y-3 ml-8">
        <div className="flex flex-wrap gap-1.5">
          {signals.map((s) => (
            <SignalBadge key={s.label} signal={s} />
          ))}
        </div>
        {desc ? (
          <p className="text-on-surface-variant text-sm line-clamp-2">{desc}</p>
        ) : null}
      </div>
    </div>
  );
}
