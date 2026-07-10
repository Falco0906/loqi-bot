"use client";

import { useState } from "react";

import type { LeadIntelligence } from "../../lib/types";

function FitScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const color =
    pct >= 80
      ? "bg-emerald-400"
      : pct >= 50
        ? "bg-amber-400"
        : "bg-rose-400";

  return (
    <div className="flex-1">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
          Fit Score
        </span>
        <span className="text-sm font-semibold text-white">{pct}%</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-white/8">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function ConfidenceRing({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;
  const color =
    pct >= 80
      ? "#34d399"
      : pct >= 50
        ? "#fbbf24"
        : "#fb7185";

  return (
    <div className="flex shrink-0 flex-col items-center">
      <svg width="64" height="64" viewBox="0 0 64 64" className="-rotate-90">
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="5"
        />
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-700"
        />
      </svg>
      <span className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
        Confidence
      </span>
      <span className="mt-0.5 text-xs font-semibold text-white">{pct}%</span>
    </div>
  );
}

function UrgencyBadge({ value }: { value: string }) {
  const label = value.toUpperCase();
  const color =
    value === "high"
      ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
      : value === "medium"
        ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
        : "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] ${color}`}
    >
      {label}
    </span>
  );
}

function StageBadge({ value }: { value: string }) {
  const label = value.charAt(0).toUpperCase() + value.slice(1);
  const color =
    value === "decision"
      ? "border-violet-400/30 bg-violet-400/10 text-violet-200"
      : value === "consideration"
        ? "border-blue-400/30 bg-blue-400/10 text-blue-200"
        : "border-slate-400/30 bg-slate-400/10 text-slate-200";

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] ${color}`}
    >
      {label}
    </span>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
        {label}
      </div>
      <div className="mt-0.5 text-sm leading-5 text-[#edf1ff]">{children}</div>
    </div>
  );
}

type Props = {
  intelligence: LeadIntelligence;
};

export default function LeadIntelligenceCard({ intelligence }: Props) {
  const [summaryOpen, setSummaryOpen] = useState(false);

  if (!intelligence) {
    return null;
  }

  return (
    <div className="mt-4 overflow-hidden rounded-[0.95rem] border border-white/8 bg-[#1a1e29]">
      {/* Top row: Fit Score bar + Confidence ring */}
      <div className="flex items-start gap-5 px-4 pb-4 pt-4">
        <FitScoreBar value={intelligence.fit_score} />
        <ConfidenceRing value={intelligence.confidence} />
      </div>

      {/* Badges row */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-5">
        <StageBadge value={intelligence.buying_stage} />
        <UrgencyBadge value={intelligence.urgency} />
      </div>

      {/* Why Selected */}
      {Array.isArray(intelligence.why_selected) && intelligence.why_selected.length > 0 ? (
        <div className="border-t border-white/8 px-4 pb-5 pt-4">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
            Why Selected
          </div>
          <ul className="m-0 space-y-1.5 pl-4">
            {intelligence.why_selected.map((reason, idx) => (
              <li
                key={idx}
                className="list-disc pl-0.5 text-[13px] leading-5 text-[#edf1ff] marker:text-[#5e63ee]"
              >
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Recommended Pitch — callout box */}
      {intelligence.recommended_pitch ? (
        <div className="border-t border-white/8 px-4 pb-5 pt-4">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3]">
            Recommended Pitch
          </div>
          <div className="rounded-[0.85rem] border border-[#5e63ee]/20 bg-[#5e63ee]/6 px-3.5 py-3 text-sm leading-5 text-[#d6dbff]">
            {intelligence.recommended_pitch}
          </div>
        </div>
      ) : null}

      {/* Info rows */}
      <div className="flex flex-col gap-3.5 border-t border-white/8 px-4 pb-5 pt-4">
        {intelligence.decision_authority_summary ? (
          <InfoRow label="Decision Authority">
            {intelligence.decision_authority_summary}
          </InfoRow>
        ) : null}

        {intelligence.estimated_business_need ? (
          <InfoRow label="Estimated Business Need">
            {intelligence.estimated_business_need}
          </InfoRow>
        ) : null}

        {intelligence.objection_risk ? (
          <InfoRow label="Objection Risk">
            {intelligence.objection_risk}
          </InfoRow>
        ) : null}

        {intelligence.best_contact_reason ? (
          <InfoRow label="Best Contact Reason">
            {intelligence.best_contact_reason}
          </InfoRow>
        ) : null}

        {intelligence.summary ? (
          <div>
            <button
              type="button"
              onClick={() => setSummaryOpen((current) => !current)}
              className="flex w-full items-center justify-between rounded-lg bg-white/[0.03] px-3.5 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.12em] text-[#8e98b3] transition hover:bg-white/[0.06]"
            >
              Summary
              <svg
                viewBox="0 0 24 24"
                className={`h-3.5 w-3.5 transition-transform duration-200 ${summaryOpen ? "rotate-180" : ""}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {summaryOpen ? (
              <div className="mt-2 text-sm leading-5 text-[#bec7dc]">
                {intelligence.summary}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
