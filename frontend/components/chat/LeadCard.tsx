"use client";

import type { Lead, LeadIntelligence } from "../../lib/types";

function FitScoreBadge({ score }: { score?: number }) {
  if (score == null) return null;
  const pct = Math.min(100, Math.max(0, Math.round(score * 100 / 150)));
  const color =
    pct >= 80
      ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
      : pct >= 50
        ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
        : "border-rose-400/30 bg-rose-400/10 text-rose-200";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${color}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          pct >= 80
            ? "bg-emerald-400"
            : pct >= 50
              ? "bg-amber-400"
              : "bg-rose-400"
        }`}
      />
      {pct}% fit
    </span>
  );
}

type LeadCardProps = {
  lead: Lead;
  index: number;
  selected: boolean;
  previewing: boolean;
  previewData: LeadIntelligence | null;
  onSelect: (index: number) => void;
  onPreview: (index: number) => void;
};

function getWhySelectedPreview(lead: Lead): string | null {
  const highlights = lead.commercial_score_breakdown?.highlights;
  if (highlights && highlights.length > 0) {
    return highlights[0];
  }
  return null;
}

export default function LeadCard({
  lead,
  index,
  selected,
  previewing,
  previewData,
  onSelect,
  onPreview,
}: LeadCardProps) {
  const name = lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Unknown";
  const title = lead.title || "";
  const company = lead.company || "";
  const whySelected = getWhySelectedPreview(lead);

  return (
    <div
      className={`rounded-[0.95rem] border p-3.5 transition-all duration-200 ${
        selected
          ? "border-[#5e63ee]/40 bg-[#5e63ee]/8 shadow-[0_0_24px_rgba(94,99,238,0.12)]"
          : "border-white/8 bg-black/10 hover:border-white/15 hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.24em] text-[#8e98b3]">
            Lead {index}
          </div>
          <div className="mt-1.5 text-sm font-semibold text-white truncate">
            {name}
          </div>
          <div className="mt-0.5 text-xs text-[#bec7dc] truncate">
            {[title, company].filter(Boolean).join(" @ ")}
          </div>
        </div>
        <FitScoreBadge score={lead.commercial_score} />
      </div>

      {whySelected ? (
        <div className="mt-2.5 text-[12px] leading-4 text-[#8e98b3] line-clamp-1">
          {whySelected}
        </div>
      ) : null}

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onSelect(index)}
          disabled={selected}
          className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold transition ${
            selected
              ? "bg-[#5e63ee]/20 text-[#5e63ee] cursor-default"
              : "bg-[#5e63ee] text-white hover:brightness-110 active:brightness-95"
          }`}
        >
          {selected ? "Selected" : "Select"}
        </button>
        <button
          type="button"
          onClick={() => onPreview(index)}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-[#bec7dc] transition hover:border-white/20 hover:bg-white/[0.08] active:bg-white/[0.03]"
        >
          Preview
        </button>
      </div>

      {previewing && previewData ? (
        <div className="mt-3 space-y-2.5 border-t border-white/8 pt-3">
          <PreviewRow label="Decision Authority">{previewData.decision_authority_summary}</PreviewRow>
          <PreviewRow label="Business Need">{previewData.estimated_business_need}</PreviewRow>
          <PreviewRow label="Recommended Pitch">{previewData.recommended_pitch}</PreviewRow>
          <PreviewRow label="Objection Risk">{previewData.objection_risk}</PreviewRow>
          <PreviewRow label="Summary">{previewData.summary}</PreviewRow>
        </div>
      ) : null}
    </div>
  );
}

function PreviewRow({ label, children }: { label: string; children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
        {label}
      </div>
      <div className="mt-0.5 text-[12px] leading-4 text-[#edf1ff]">{children}</div>
    </div>
  );
}
