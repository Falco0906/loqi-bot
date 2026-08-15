"use client";

import { memo, useState } from "react";
import Icon from "../shared/Icon";

type StrategySection = {
  key: string;
  title: string;
  icon: string;
  render: () => React.ReactNode;
};

type StrategyGroupDef = {
  key: string;
  title: string;
  icon: string;
  blurb: string;
};

const GROUP_DEFS: StrategyGroupDef[] = [
  {
    key: "overview",
    title: "Overview",
    icon: "speed",
    blurb: "What we are selling, to whom, and how confident we are",
  },
  {
    key: "market",
    title: "Market Intelligence",
    icon: "public",
    blurb: "Signals, patterns, technologies and risks in the market",
  },
  {
    key: "sales",
    title: "Sales Strategy",
    icon: "rocket_launch",
    blurb: "Messaging, positioning, sequence and offer",
  },
  {
    key: "objections",
    title: "Objections & Proof",
    icon: "verified",
    blurb: "Pains, objections, proof points and differentiators",
  },
  {
    key: "personas",
    title: "Personas",
    icon: "groups",
    blurb: "Who writes, who reads, and the tone in between",
  },
  {
    key: "additional",
    title: "Additional Details",
    icon: "more_horiz",
    blurb: "Everything else the playbook covers",
  },
];

const SECTION_GROUP: Record<string, string> = {
  objective: "overview",
  audience: "overview",
  market: "overview",
  confidence: "overview",
  market_attractiveness: "market",
  market_maturity: "market",
  market_common_patterns: "market",
  market_technologies: "market",
  patterns: "market",
  buying_signals: "market",
  why_now: "market",
  risks: "market",
  value_proposition: "sales",
  positioning: "sales",
  messaging_angles: "sales",
  messaging: "sales",
  personalization: "sales",
  outreach_strategy: "sales",
  cta: "sales",
  offer: "sales",
  pain_points: "objections",
  pain_prioritization: "objections",
  objections: "objections",
  proof_points: "objections",
  differentiators: "objections",
  persona: "personas",
  audience_personas: "personas",
  tone: "personas",
  success: "additional",
};

function toText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function textOrNull(value: unknown): string | null {
  const t = toText(value);
  return t.length > 0 ? t : null;
}

function listFrom(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String).filter((x) => x.trim().length > 0);
  }
  const t = toText(value);
  return t.length > 0 ? [t] : [];
}

function objectListFrom(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (x): x is Record<string, unknown> =>
      typeof x === "object" && x !== null && !Array.isArray(x),
  );
}

function dictFrom(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function bullets(values: string[], icon?: string) {
  return (
    <ul className="space-y-1.5">
      {values.map((v, i) => (
        <li key={i} className="text-on-surface flex items-start gap-2">
          <span className={icon === "error" ? "text-error mt-0.5" : "text-primary mt-0.5"}>•</span>
          <span className="leading-relaxed">{v}</span>
        </li>
      ))}
    </ul>
  );
}

function offerToLines(offer: unknown): string[] {
  if (!offer || typeof offer !== "object") return [];
  const lines: string[] = [];
  const entries = Object.entries(offer as Record<string, unknown>);
  for (const [k, v] of entries) {
    const label = k.replace(/_/g, " ");
    if (v == null || v === "") continue;
    if (typeof v === "object") {
      lines.push(`${label}: ${Object.entries(v as Record<string, unknown>).map(([kk, vv]) => String(vv)).join(", ")}`);
    } else {
      lines.push(`${label}: ${String(v)}`);
    }
  }
  return lines;
}

/**
 * Strategy rendered as a document, not metadata.
 *
 * Renders the Sales Playbook: objective, ICP, market summary, observed
 * patterns, buying signals, pain points, value proposition, positioning,
 * messaging angles, persona, offer, outreach sequence, personalization,
 * tone, objections, CTA, success metrics, risks and confidence.
 *
 * Sections with no data are omitted. The artifact may arrive flat (fresh
 * generation response) or nested under `content` (persisted raw dict);
 * both are merged before rendering, so no component change is required to
 * render richer strategies.
 */
export default memo(function StrategyDocument({
  objective,
  strategy,
  generating,
}: {
  objective: string;
  strategy: Record<string, unknown> | null | undefined;
  generating?: boolean;
}) {
  const s = strategy || {};
  const content = s.content && typeof s.content === "object" ? (s.content as Record<string, unknown>) : {};
  const all = { ...s, ...content };
  const offer = s.offer && typeof s.offer === "object" ? (s.offer as Record<string, unknown>) : {};

  const objectiveText = textOrNull(s.objective) || textOrNull(all.campaign_objective) || textOrNull(objective);
  const audience = textOrNull(s.audience);
  const icp = textOrNull(all.icp) || textOrNull(audience);
  const marketSummary = textOrNull(all.market_summary);
  const observedPatterns = listFrom(all.observed_patterns);
  const buyingSignals = listFrom(all.buying_signals);
  const painPoints = textOrNull(all.pain_points);
  const valueProposition = textOrNull(all.value_proposition);
  const positioning = textOrNull(all.positioning) || textOrNull(s.messaging_angle);
  const messagingAngles = listFrom(all.messaging_angles);
  const persona = textOrNull(all.persona);
  const tone = textOrNull(s.tone) || textOrNull(all.tone);
  const channel = textOrNull(s.channel) || textOrNull(all.channel);
  const cta = textOrNull(all.cta) || textOrNull(offer.detail) || textOrNull(offer.type);
  const personalization = textOrNull(all.personalization);
  const successMetrics = listFrom(all.success_metrics).length > 0 ? listFrom(all.success_metrics) : listFrom(all.success_criteria);
  const risks = listFrom(all.risks);
  const confidence = textOrNull(all.confidence);

  const marketAttractiveness = textOrNull(all.market_attractiveness);
  const marketMaturity = textOrNull(all.market_maturity);
  const marketCommonPatterns = listFrom(all.market_common_patterns);
  const marketTechnologies = listFrom(all.market_technologies);
  const painPrioritization = objectListFrom(all.pain_prioritization);
  const personas = objectListFrom(all.personas);
  const differentiators = listFrom(all.differentiators);
  const proofPoints = listFrom(all.proof_points);
  const whyNow = textOrNull(all.why_now);
  const outreachStrategy = dictFrom(all.outreach_strategy);

  const sequence =
    listFrom(all.outreach_sequence).length > 0
      ? listFrom(all.outreach_sequence)
      : Array.isArray(s.sequence)
        ? s.sequence.map(String).filter((x) => x.trim().length > 0)
        : [];
  const objections =
    listFrom(all.objection_handling).length > 0
      ? listFrom(all.objection_handling)
      : Array.isArray(s.objections)
        ? s.objections.map(String).filter((x) => x.trim().length > 0)
        : [];
  const offerLines = offerToLines(offer);

  if (generating) {
    return (
      <div className="p-6 rounded-xl border border-outline-variant/10 bg-surface-lowest space-y-4">
        <div className="flex items-center gap-3">
          <span className="w-5 h-5 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-on-surface-variant">Loqi is drafting the strategy…</p>
        </div>
        <div className="space-y-2.5">
          <div className="h-3 w-3/4 bg-surface-high/50 rounded animate-skeleton-pulse" />
          <div className="h-3 w-2/3 bg-surface-high/50 rounded animate-skeleton-pulse" />
          <div className="h-3 w-1/2 bg-surface-high/50 rounded animate-skeleton-pulse" />
        </div>
      </div>
    );
  }

  const sections: StrategySection[] = [
    ...(objectiveText
      ? [{
          key: "objective",
          title: "Campaign Objective",
          icon: "speed",
          render: () => <p className="text-on-surface leading-relaxed">{objectiveText}</p>,
        }]
      : []),
    ...(icp || audience
      ? [{
          key: "audience",
          title: "Ideal Customer Profile",
          icon: "groups",
          render: () => <p className="text-on-surface leading-relaxed">{icp || audience}</p>,
        }]
      : []),
    ...(marketSummary
      ? [{
          key: "market",
          title: "Market Summary",
          icon: "public",
          render: () => <p className="text-on-surface leading-relaxed">{marketSummary}</p>,
        }]
      : []),
    ...(marketAttractiveness
      ? [{
          key: "market_attractiveness",
          title: "Market Attractiveness",
          icon: "insights",
          render: () => <p className="text-on-surface leading-relaxed">{marketAttractiveness}</p>,
        }]
      : []),
    ...(marketMaturity
      ? [{
          key: "market_maturity",
          title: "Market Maturity",
          icon: "timeline",
          render: () => <p className="text-on-surface leading-relaxed">{marketMaturity}</p>,
        }]
      : []),
    ...(marketCommonPatterns.length > 0
      ? [{
          key: "market_common_patterns",
          title: "Common Market Patterns",
          icon: "category",
          render: () => bullets(marketCommonPatterns),
        }]
      : []),
    ...(marketTechnologies.length > 0
      ? [{
          key: "market_technologies",
          title: "Technologies in Use",
          icon: "memory",
          render: () => bullets(marketTechnologies),
        }]
      : []),
    ...(observedPatterns.length > 0
      ? [{
          key: "patterns",
          title: "Observed Patterns",
          icon: "insights",
          render: () => bullets(observedPatterns),
        }]
      : []),
    ...(buyingSignals.length > 0
      ? [{
          key: "buying_signals",
          title: "Buying Signals",
          icon: "trending_up",
          render: () => bullets(buyingSignals),
        }]
      : []),
    ...(painPoints
      ? [{
          key: "pain_points",
          title: "Pain Points",
          icon: "warning",
          render: () => <p className="text-on-surface leading-relaxed">{painPoints}</p>,
        }]
      : []),
    ...(painPrioritization.length > 0
      ? [{
          key: "pain_prioritization",
          title: "Pain Prioritization",
          icon: "format_list_numbered",
          render: () => (
            <ul className="space-y-3">
              {painPrioritization.map((p, i) => {
                const pain = textOrNull(p.pain);
                const why = textOrNull(p.why);
                if (!pain && !why) return null;
                return (
                  <li key={i} className="text-on-surface flex items-start gap-2">
                    <span className="text-primary mt-0.5 shrink-0">•</span>
                    <span className="leading-relaxed">
                      {pain && <span className="font-medium">{pain}</span>}
                      {pain && why && <span className="text-on-surface-variant"> — </span>}
                      {why && <span className="text-on-surface-variant">{why}</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          ),
        }]
      : []),
    ...(valueProposition
      ? [{
          key: "value_proposition",
          title: "Value Proposition",
          icon: "volunteer_activism",
          render: () => <p className="text-on-surface leading-relaxed">{valueProposition}</p>,
        }]
      : []),
    ...(positioning
      ? [{
          key: "positioning",
          title: "Positioning",
          icon: "explore",
          render: () => <p className="text-on-surface leading-relaxed">{positioning}</p>,
        }]
      : []),
    ...(messagingAngles.length > 0
      ? [{
          key: "messaging_angles",
          title: "Messaging Angles",
          icon: "edit_note",
          render: () => bullets(messagingAngles),
        }]
      : []),
    ...(differentiators.length > 0
      ? [{
          key: "differentiators",
          title: "Differentiators",
          icon: "star",
          render: () => bullets(differentiators),
        }]
      : []),
    ...(proofPoints.length > 0
      ? [{
          key: "proof_points",
          title: "Proof Points",
          icon: "verified",
          render: () => bullets(proofPoints),
        }]
      : []),
    ...(persona
      ? [{
          key: "persona",
          title: "Sender Persona",
          icon: "psychology",
          render: () => <p className="text-on-surface leading-relaxed">{persona}</p>,
        }]
      : []),
    ...(personas.length > 0
      ? [{
          key: "audience_personas",
          title: "Audience Personas",
          icon: "groups",
          render: () => (
            <ul className="space-y-3.5">
              {personas.map((p, i) => {
                const inner = [
                  textOrNull(p.persona),
                  textOrNull(p.authority_level),
                  textOrNull(p.priorities),
                  textOrNull(p.incentives),
                  textOrNull(p.kpis),
                  textOrNull(p.fears),
                  listFrom(p.likely_objections),
                ];
                const hasContent = inner.some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(v)));
                if (!hasContent) return null;
                return (
                  <li key={i} className="space-y-1">
                    <p className="text-on-surface font-medium">{textOrNull(p.persona) || `Persona ${i + 1}`}</p>
                    {textOrNull(p.priorities) && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">
                        Priorities: {textOrNull(p.priorities)}
                      </p>
                    )}
                    {textOrNull(p.incentives) && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">
                        What motivates: {textOrNull(p.incentives)}
                      </p>
                    )}
                    {textOrNull(p.kpis) && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">Measured by: {textOrNull(p.kpis)}</p>
                    )}
                    {textOrNull(p.fears) && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">Fears: {textOrNull(p.fears)}</p>
                    )}
                    {textOrNull(p.authority_level) && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">Authority: {textOrNull(p.authority_level)}</p>
                    )}
                    {listFrom(p.likely_objections).length > 0 && (
                      <p className="text-on-surface-variant text-sm leading-relaxed">
                        Likely objections: {listFrom(p.likely_objections).join("; ")}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          ),
        }]
      : []),
    ...(offerLines.length > 0
      ? [{
          key: "offer",
          title: "Offer",
          icon: "add_business",
          render: () => (
            <ul className="space-y-1.5">
              {offerLines.map((line, i) => (
                <li key={i} className="text-on-surface flex items-start gap-2">
                  <span className="text-primary mt-0.5">•</span>
                  <span className="capitalize-first">{line}</span>
                </li>
              ))}
            </ul>
          ),
        }]
      : []),
    ...(sequence.length > 0
      ? [{
          key: "messaging",
          title: "Outreach Sequence",
          icon: "forum",
          render: () => (
            <ol className="space-y-2">
              {sequence.map((step, i) => (
                <li key={i} className="flex items-start gap-3 text-on-surface">
                  <span className="w-5 h-5 rounded-full bg-primary/10 text-primary text-[11px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  <span className="leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
          ),
        }]
      : []),
        ...(personalization
      ? [{
          key: "personalization",
          title: "Personalization",
          icon: "auto_fix_high",
          render: () => <p className="text-on-surface leading-relaxed">{personalization}</p>,
        }]
      : []),
    ...(Object.keys(outreachStrategy).length > 0
      ? [{
          key: "outreach_strategy",
          title: "Outreach Strategy",
          icon: "rocket_launch",
          render: () => (
            <ul className="space-y-2">
              {[
                [textOrNull(outreachStrategy.first_touch_goal), "First-touch goal"],
                [textOrNull(outreachStrategy.first_touch_cta), "First-touch CTA"],
                [textOrNull(outreachStrategy.follow_up_strategy), "Follow-up strategy"],
              ].map(([text, label]) =>
                text ? (
                  <li key={label} className="text-on-surface flex items-start gap-2">
                    <span className="text-primary mt-0.5 shrink-0">•</span>
                    <span className="leading-relaxed">
                      <span className="text-on-surface-variant">{label}: </span>
                      {text}
                    </span>
                  </li>
                ) : null,
              )}
              {listFrom(outreachStrategy.personalization_opportunities).length > 0 && (
                <li className="text-on-surface flex items-start gap-2">
                  <span className="text-primary mt-0.5 shrink-0">•</span>
                  <span className="leading-relaxed">
                    <span className="text-on-surface-variant">Personalization opportunities: </span>
                    {listFrom(outreachStrategy.personalization_opportunities).join("; ")}
                  </span>
                </li>
              )}
              {listFrom(outreachStrategy.topics_to_avoid).length > 0 && (
                <li className="text-on-surface flex items-start gap-2">
                  <span className="text-error mt-0.5 shrink-0">•</span>
                  <span className="leading-relaxed">
                    <span className="text-on-surface-variant">Topics to avoid: </span>
                    {listFrom(outreachStrategy.topics_to_avoid).join("; ")}
                  </span>
                </li>
              )}
            </ul>
          ),
        }]
      : []),
    ...(whyNow
      ? [{
          key: "why_now",
          title: "Why Now",
          icon: "bolt",
          render: () => <p className="text-on-surface leading-relaxed">{whyNow}</p>,
        }]
      : []),
    ...(tone
      ? [{
          key: "tone",
          title: "Tone",
          icon: "tune",
          render: () => (
            <div className="flex flex-wrap gap-2">
              <span className="px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface text-xs font-medium capitalize">{tone}</span>
              {channel ? <span className="px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface text-xs font-medium">{channel}</span> : null}
            </div>
          ),
        }]
      : []),
    ...(objections.length > 0
      ? [{
          key: "objections",
          title: "Objections to Anticipate",
          icon: "help_outline",
          render: () => bullets(objections, "error"),
        }]
      : []),
    ...(cta
      ? [{
          key: "cta",
          title: "Call to Action",
          icon: "arrow_forward",
          render: () => <p className="text-on-surface leading-relaxed">{cta}</p>,
        }]
      : []),
    ...(successMetrics.length > 0
      ? [{
          key: "success",
          title: "Success Metrics",
          icon: "check_circle",
          render: () => bullets(successMetrics),
        }]
      : []),
    ...(risks.length > 0
      ? [{
          key: "risks",
          title: "Risks",
          icon: "report_problem",
          render: () => bullets(risks, "error"),
        }]
      : []),
    ...(confidence
      ? [{
          key: "confidence",
          title: "Confidence",
          icon: "fact_check",
          render: () => <p className="text-on-surface leading-relaxed">{confidence}</p>,
        }]
      : []),
  ];

  if (sections.length === 0) {
    return (
      <div className="p-6 rounded-xl border border-outline-variant/10 bg-surface-lowest text-center">
        <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary mx-auto mb-3">
          <Icon name="auto_awesome" className="text-2xl" />
        </div>
        <p className="text-sm text-on-surface-variant/80 font-medium">No strategy yet</p>
        <p className="mt-1 text-xs text-on-surface-variant/50 max-w-sm mx-auto leading-relaxed">
          Loqi will turn this campaign objective into a full outreach strategy — audience, messaging, sequence and offer.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {GROUP_DEFS.map((group) => {
        const groupSections = sections.filter(
          (section) => (SECTION_GROUP[section.key] ?? "additional") === group.key,
        );
        if (groupSections.length === 0) return null;
        return (
          <StrategyGroupBlock key={group.key} group={group} sections={groupSections} />
        );
      })}
    </div>
  );
});

function StrategyGroupBlock({
  group,
  sections,
}: {
  group: StrategyGroupDef;
  sections: StrategySection[];
}) {
  const [open, setOpen] = useState(group.key === "overview");
  return (
    <section className="bg-surface-lowest border border-outline-variant/10 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left hover:bg-surface-container-low transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
            <Icon name={group.icon} className="text-sm" />
          </span>
          <div className="min-w-0">
            <h4 className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 font-semibold">
              {group.title}
            </h4>
            {!open && (
              <p className="text-xs text-on-surface-variant/50 truncate mt-0.5">{group.blurb}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/40 font-medium">
            {sections.length} {sections.length === 1 ? "item" : "items"}
          </span>
          <span
            className={`material-symbols-outlined text-on-surface-variant/60 transition-transform ${open ? "rotate-180" : ""}`}
          >
            expand_more
          </span>
        </div>
      </button>
      {open && (
        <div className="px-5 pb-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          {sections.map((section) => (
            <section
              key={section.key}
              className="p-5 rounded-xl border border-outline-variant/10 bg-surface-container-low/40"
            >
              <div className="flex items-center gap-2 mb-3">
                <span className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                  <Icon name={section.icon} className="text-sm" />
                </span>
                <h5 className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 font-semibold">
                  {section.title}
                </h5>
              </div>
              {section.render()}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
