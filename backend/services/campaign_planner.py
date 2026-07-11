import uuid
from typing import Any


SIGNAL_PATTERNS: list[tuple[str, list[str], str, str, str]] = [
    (
        "Operational Expansion",
        [
            "expansion", "expanding", "new location", "new office",
            "growing", "scale", "scaling", "opening", "new market",
            "geographic", "multi-location", "new facility",
        ],
        "primary_signal",
        "Recently expanding operations or opening new locations.",
        "Help operations scale without increasing manual coordination overhead.",
    ),
    (
        "Hiring & Talent",
        [
            "hiring", "recruit", "talent", "headcount", "hiring manager",
            "operations leader", "hiring operations", "talent acquisition",
            "recruiting", "hr", "people team", "workforce",
        ],
        "primary_signal",
        "Actively hiring for key roles across the organization.",
        "Reduce onboarding and coordination overhead for growing teams.",
    ),
    (
        "Technology Adoption",
        [
            "salesforce", "hubspot", "crm", "salesforce.com", "sfdc",
            "modern sales", "sales stack", "outbound tool", "sales tech",
            "revenue operations", "revops", "sales engagement",
        ],
        "primary_signal",
        "Already using modern sales and CRM platforms.",
        "Improve outbound efficiency without replacing existing tools.",
    ),
    (
        "Growth Stage",
        [
            "series a", "series b", "series c", "funding", "fundraise",
            "venture capital", "vc backed", "investor", "raised",
            "seed", "growth stage", "high growth",
        ],
        "primary_signal",
        "Well-funded and in a growth phase with dedicated budget.",
        "Position Loqi as a force multiplier for their existing growth investments.",
    ),
    (
        "Digital Transformation",
        [
            "digital transform", "digitalization", "automation",
            "digital initiative", "modernize", "modernization",
            "digital strategy", "innovation", "digital first",
        ],
        "primary_signal",
        "Investing in digital transformation initiatives.",
        "Accelerate their digital roadmap with AI-native outbound infrastructure.",
    ),
    (
        "Competitive Pressure",
        [
            "competitor", "competitive", "market pressure",
            "market share", "market leader", "competitive landscape",
            "industry shift", "disruption", "new entrant",
        ],
        "primary_signal",
        "Operating in a competitive landscape with pressure to differentiate.",
        "Win through personalized, AI-driven outreach at scale.",
    ),
]


INDUSTRY_CAMPAIGNS: list[tuple[str, list[str], str, str]] = [
    (
        "Enterprise Technology",
        ["software", "saas", "technology", "tech", "it", "cloud", "enterprise software"],
        "Leading technology organization seeking operational leverage.",
        "Streamline outbound with AI that learns your stack, not fights it.",
    ),
    (
        "Professional Services",
        ["consulting", "services", "professional services", "agency", "advisory"],
        "Relationship-driven business where personalization matters most.",
        "Scale one-to-one outreach without sacrificing the personal touch.",
    ),
    (
        "Financial Services",
        ["finance", "banking", "insurance", "fintech", "financial", "investment"],
        "Regulated industry where compliance and precision are critical.",
        "Deploy compliant, high-precision outreach with full audit trails.",
    ),
    (
        "Healthcare & Life Sciences",
        ["healthcare", "health", "medical", "pharma", "biotech", "life sciences", "health tech"],
        "Mission-critical industry where timing and trust drive decisions.",
        "Reach decision-makers with relevant, timely, and trustworthy messaging.",
    ),
    (
        "Manufacturing & Industrial",
        ["manufacturing", "industrial", "logistics", "supply chain", "factory", "production"],
        "Traditional industry modernizing sales and customer engagement.",
        "Bring modern outbound efficiency to industrial sales teams.",
    ),
]


def _match_signals(lead: dict[str, Any]) -> list[str]:
    matched: list[str] = []
    signals = lead.get("buying_signals")
    if isinstance(signals, list):
        for s in signals:
            if isinstance(s, str):
                matched.append(s.lower())

    events = lead.get("recent_events")
    if isinstance(events, list):
        for e in events:
            if isinstance(e, str):
                matched.append(e.lower())

    desc = lead.get("company_description")
    if isinstance(desc, str):
        matched.append(desc.lower())

    growth = lead.get("company_growth_stage")
    if isinstance(growth, str):
        matched.append(growth.lower())

    return matched


def _score_campaign(lead_signals: list[str], pattern_keywords: list[str]) -> float:
    score = 0.0
    for signal in lead_signals:
        for kw in pattern_keywords:
            if kw in signal:
                score += 2.0
                break
    return score


def _assign_industry(lead: dict[str, Any]) -> str | None:
    industry = lead.get("company_industry")
    if isinstance(industry, str):
        ind_lower = industry.lower()
        for name, keywords, _reason, _angle in INDUSTRY_CAMPAIGNS:
            for kw in keywords:
                if kw in ind_lower:
                    return name
    return None


def _infer_message_theme(lead: dict[str, Any], campaign_name: str) -> str:
    name = lead.get("name") or ""
    company = lead.get("company") or ""
    first = name.split()[0] if name else "there"

    themes: dict[str, str] = {
        "Operational Expansion": f"Hi {first}, I noticed {company}'s recent expansion. ",
        "Hiring & Talent": f"Hi {first}, I saw {company} is growing your team. ",
        "Technology Adoption": f"Hi {first}, I see {company} uses modern sales tools. ",
        "Growth Stage": f"Hi {first}, congrats on {company}'s growth. ",
        "Digital Transformation": f"Hi {first}, I see {company} is investing in digital innovation. ",
        "Competitive Pressure": f"Hi {first}, I know {company} is navigating a shifting landscape. ",
    }
    return themes.get(
        campaign_name,
        f"Hi {first}, I've been following {company}'s progress. ",
    )


def analyze_campaigns(leads: list[dict[str, Any]]) -> dict[str, Any]:
    if not leads:
        return {
            "ok": True,
            "plan_id": str(uuid.uuid4()),
            "campaigns": [],
            "overall_recommendation": "No leads provided for analysis.",
            "total_leads": 0,
        }

    scored: dict[str, list[tuple[int, dict[str, Any], float]]] = {
        name: [] for name, *_ in SIGNAL_PATTERNS
    }
    industry_fallback: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    unassigned: list[tuple[int, dict[str, Any]]] = []

    for i, lead in enumerate(leads):
        lead_signals = _match_signals(lead)
        best_score = 0.0
        best_campaign: str | None = None

        for name, keywords, _type, _reason, _angle in SIGNAL_PATTERNS:
            s = _score_campaign(lead_signals, keywords)
            if s > best_score:
                best_score = s
                best_campaign = name

        if best_campaign and best_score >= 2.0:
            scored[best_campaign].append((i, lead, best_score))
        else:
            ind = _assign_industry(lead)
            if ind:
                if ind not in industry_fallback:
                    industry_fallback[ind] = []
                industry_fallback[ind].append((i, lead))
            else:
                unassigned.append((i, lead))

    campaigns: list[dict[str, Any]] = []

    for name, _keywords, _type, reason, angle in SIGNAL_PATTERNS:
        group = scored.get(name, [])
        if not group:
            continue
        group.sort(key=lambda x: -x[2])
        campaign_leads = [lead for _, lead, _ in group]
        first_lead = campaign_leads[0]
        campaigns.append({
            "id": str(uuid.uuid4()),
            "name": name,
            "lead_count": len(group),
            "leads": campaign_leads,
            "primary_signal": _type,
            "reason": reason,
            "messaging_angle": angle,
            "priority": min(len(group), 5),
            "message_theme": _infer_message_theme(first_lead, name),
        })

    for ind_name, _ind_keywords, _ind_reason, _ind_angle in INDUSTRY_CAMPAIGNS:
        group = industry_fallback.get(ind_name, [])
        if not group:
            continue
        campaign_leads = [lead for _, lead in group]
        first_lead = campaign_leads[0]
        campaigns.append({
            "id": str(uuid.uuid4()),
            "name": ind_name,
            "lead_count": len(group),
            "leads": campaign_leads,
            "primary_signal": "industry",
            "reason": f"Organized by industry vertical to tailor messaging to {ind_name.lower()} pain points.",
            "messaging_angle": f"Address the specific challenges facing {ind_name.lower()} buyers.",
            "priority": min(len(group), 3),
            "message_theme": _infer_message_theme(first_lead, ind_name),
        })

    if unassigned:
        campaign_leads = [lead for _, lead in unassigned]
        first_lead = campaign_leads[0]
        campaigns.append({
            "id": str(uuid.uuid4()),
            "name": "Diverse Opportunities",
            "lead_count": len(unassigned),
            "leads": campaign_leads,
            "primary_signal": "mixed",
            "reason": "Grouped for broad outreach with varied messaging approaches.",
            "messaging_angle": "Test multiple angles and optimize based on response.",
            "priority": 1,
            "message_theme": _infer_message_theme(first_lead, "Diverse Opportunities"),
        })

    campaigns.sort(key=lambda c: (-c["priority"], -c["lead_count"]))

    total = len(leads)
    campaign_lines = "\n".join(
        f"- **{c['name']}** ({c['lead_count']} leads): {c['reason']}"
        for c in campaigns
    )

    overview = (
        f"I recommend splitting {total} lead{'s' if total != 1 else ''} "
        f"into {len(campaigns)} campaign{'s' if len(campaigns) != 1 else ''}.\n\n"
        f"This increases personalization while keeping messaging consistent "
        f"across similar buying situations.\n\n{campaign_lines}"
    ) if campaigns else "No campaign groupings could be determined."

    return {
        "ok": True,
        "plan_id": str(uuid.uuid4()),
        "campaigns": campaigns,
        "overall_recommendation": overview,
        "total_leads": total,
    }
