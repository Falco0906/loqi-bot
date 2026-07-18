"use client";

import Icon from "../shared/Icon";

type ReasoningDecision = {
  type: string;
  priority: string;
  risk: string;
  confidence: number;
  primary_goal: string | null;
  alternative_goal: string | null;
  evidence: string[];
  reasoning: string[];
  policy_results: { policy: string; result: string; reasoning: string }[];
};

type ReasoningPanelProps = {
  reasoning: {
    decision: ReasoningDecision;
    goal: { primary: string; alternative: string | null; reasoning: string[] };
    priority: { level: string; score: number; max_score: number; factors: Record<string, number>; reasoning: string[] };
    risk: { level: string; score: number; max_score: number; factors: string[]; evidence: string[] };
    confidence: { overall: number; intent_confidence: number; signal_confidence: number; objection_confidence: number; entity_confidence: number; completeness: number; breakdown: string[] };
  };
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: "text-red-400 border-red-500/30 bg-red-500/10",
  high: "text-amber-400 border-amber-500/30 bg-amber-500/10",
  medium: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  low: "text-green-400 border-green-500/30 bg-green-500/10",
};

const RISK_COLORS: Record<string, string> = {
  high: "text-red-400 border-red-500/30 bg-red-500/10",
  medium: "text-amber-400 border-amber-500/30 bg-amber-500/10",
  low: "text-green-400 border-green-500/30 bg-green-500/10",
};

const DECISION_ICONS: Record<string, string> = {
  reply: "reply",
  wait: "schedule",
  schedule_follow_up: "timer",
  request_human_review: "person",
  escalate: "trending_up",
  book_meeting: "calendar_today",
  close_conversation: "close",
  stop_outreach: "stop",
  continue_nurturing: "auto_awesome",
  request_more_information: "help",
};

const POLICY_RESULT_COLORS: Record<string, string> = {
  passed: "text-green-400",
  failed: "text-red-400",
  requires_review: "text-amber-400",
  not_applicable: "text-on-surface-variant/50",
};

function ConfidenceRing({ value }: { value: number }) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(value, 1));
  const color = value >= 0.7 ? "#22c55e" : value >= 0.4 ? "#f59e0b" : "#ef4444";

  return (
    <div className="flex items-center gap-2">
      <svg width="44" height="44" className="shrink-0">
        <circle cx="22" cy="22" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
        <circle
          cx="22" cy="22" r={radius}
          fill="none" stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 22 22)"
          className="transition-all duration-500"
        />
      </svg>
      <span className="text-lg font-bold" style={{ color }}>{Math.round(value * 100)}%</span>
    </div>
  );
}

function ScoreBar({ value, maxValue = 100 }: { value: number; maxValue?: number }) {
  const pct = Math.min((value / maxValue) * 100, 100);
  const barColor = pct >= 70 ? "#22c55e" : pct >= 40 ? "#f59e0b" : "#ef4444";

  return (
    <div className="h-1.5 rounded-full bg-white/5 overflow-hidden mt-1.5">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, backgroundColor: barColor }}
      />
    </div>
  );
}

export default function ReasoningPanel({ reasoning }: ReasoningPanelProps) {
  const { decision, goal, priority, risk, confidence: conf } = reasoning;

  return (
    <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4 space-y-4">
      <h3 className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider">
        Reasoning
      </h3>

      {/* Recommended Decision */}
      <div className={`rounded-lg border px-3 py-2.5 ${PRIORITY_COLORS[priority.level] || "border-outline-variant/10"}`}>
        <div className="flex items-center gap-2">
          <Icon name={DECISION_ICONS[decision.type] || "more_horiz"} className="text-sm" />
          <span className="text-sm font-medium capitalize">
            {decision.type.replace(/_/g, " ")}
          </span>
        </div>
        {decision.reasoning.length > 0 && (
          <div className="mt-1.5 space-y-0.5">
            {decision.reasoning.slice(0, 3).map((r, i) => (
              <p key={i} className="text-[11px] text-on-surface-variant/60 leading-relaxed">{r}</p>
            ))}
          </div>
        )}
      </div>

      {/* Goal */}
      <div>
        <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1">Goal</span>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-on-surface/80 capitalize">{goal.primary.replace(/_/g, " ")}</span>
          {goal.alternative && (
            <>
              <span className="text-[10px] text-on-surface-variant/40">→</span>
              <span className="text-[11px] text-on-surface-variant/60 capitalize">{goal.alternative.replace(/_/g, " ")}</span>
            </>
          )}
        </div>
      </div>

      {/* Priority + Risk row */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1">Priority</span>
          <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${PRIORITY_COLORS[priority.level] || ""}`}>
            <Icon name={priority.level === "critical" ? "priority_high" : priority.level === "high" ? "arrow_upward" : priority.level === "medium" ? "remove" : "arrow_downward"} className="text-[10px]" />
            <span className="capitalize">{priority.level}</span>
          </div>
          {priority.score > 0 && (
            <ScoreBar value={priority.score} maxValue={priority.max_score} />
          )}
        </div>
        <div>
          <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1">Risk</span>
          <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${RISK_COLORS[risk.level] || ""}`}>
            <Icon name={risk.level === "high" ? "warning" : risk.level === "medium" ? "error_outline" : "check_circle"} className="text-[10px]" />
            <span className="capitalize">{risk.level}</span>
          </div>
        </div>
      </div>

      {/* Confidence */}
      <div>
        <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-2">Confidence</span>
        <ConfidenceRing value={conf.overall} />
        {conf.breakdown.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {conf.breakdown.slice(0, 3).map((b, i) => (
              <p key={i} className="text-[10px] text-on-surface-variant/50 leading-relaxed">{b}</p>
            ))}
          </div>
        )}
      </div>

      {/* Policy Results */}
      {decision.policy_results.length > 0 && (
        <div>
          <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1.5">Policies</span>
          <div className="space-y-1">
            {decision.policy_results.map((p, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className={`text-[10px] font-medium mt-0.5 ${POLICY_RESULT_COLORS[p.result] || ""}`}>
                  {p.result === "passed" ? "✓" : p.result === "failed" ? "✗" : p.result === "requires_review" ? "!" : "—"}
                </span>
                <div>
                  <span className="text-[11px] text-on-surface-variant/70">{p.policy.replace(/_/g, " ")}</span>
                  {p.reasoning && (
                    <p className="text-[10px] text-on-surface-variant/50">{p.reasoning}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Evidence */}
      {decision.evidence.length > 0 && (
        <div>
          <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1">Evidence</span>
          <ul className="space-y-0.5">
            {decision.evidence.slice(0, 5).map((e, i) => (
              <li key={i} className="text-[11px] text-on-surface-variant/60 flex items-start gap-1.5">
                <span className="text-[8px] mt-1">•</span>
                <span>{e}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
