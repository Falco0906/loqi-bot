"""Deterministic lead intelligence generator.

Produces structured sales intelligence *after* enrichment and *before*
draft generation. Explains WHY each lead was selected, what to pitch, and
what risks exist — without calling an LLM.
"""


def _log(message: str) -> None:
    print(f"[lead_intelligence] {message}")


# ---------------------------------------------------------------------------
# Buying-stage heuristics
# ---------------------------------------------------------------------------

_STAGE_KEYWORDS: dict[str, list[str]] = {
    "awareness": ["researching", "exploring", "evaluating", "considering", "looking for"],
    "consideration": ["comparing", "shortlisting", "demo", "trial", "pilot", "vendor selection"],
    "decision": ["ready to buy", "purchase", "implementation", "deployment", "rollout", "migrating", "scaling"],
}


def _infer_buying_stage(lead: dict, enrichment: dict | None) -> str:
    """Infer buying stage from buying signals, growth stage, and recent events."""
    signals = " ".join([
        " ".join(lead.get("buying_signals") or []),
        " ".join(lead.get("recent_events") or []),
        (lead.get("company_growth_stage") or ""),
    ]).lower()

    for stage, keywords in _STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in signals:
                return stage
    return "awareness"


# ---------------------------------------------------------------------------
# Urgency heuristics
# ---------------------------------------------------------------------------

_HIGH_URGENCY_SIGNALS = [
    "expanding", "new locations", "hiring", "growing", "scaling",
    "funding", "series", "acquisition", "merger", "rebrand",
    "new leadership", "ceo", "restructuring", "turnaround",
]

_MEDIUM_URGENCY_SIGNALS = [
    "upgrading", "modernizing", "replacing", "switching",
    "evaluating", "comparing", "new project", "initiative",
]


def _infer_urgency(lead: dict, enrichment: dict | None) -> str:
    signals_text = " ".join([
        " ".join(lead.get("buying_signals") or []),
        " ".join(lead.get("recent_events") or []),
        (lead.get("company_growth_stage") or ""),
    ]).lower()
    for s in _HIGH_URGENCY_SIGNALS:
        if s in signals_text:
            return "high"
    for s in _MEDIUM_URGENCY_SIGNALS:
        if s in signals_text:
            return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Objection risk heuristics
# ---------------------------------------------------------------------------

_OBJECTION_PATTERNS: list[tuple[str, str]] = [
    ("ceo", "CEO may be too busy for cold outreach — needs executive-level relevance"),
    ("vp", "VP-level may delegate — ensure message targets their strategic priorities"),
    ("director", "Director may need buy-in from above — provide clear ROI justification"),
    ("manager", "Manager may lack purchasing authority — include upward-chain value prop"),
    ("owner", "Owner has full authority but is protective of time — make it highly relevant"),
    ("founder", "Founder is time-constrained — lead with immediate business impact"),
    ("solo", "Small operation — budget may be limited"),
    ("enterprise", "Large organization — may have existing vendor relationships"),
    ("technology", "May be evaluating competitive solutions"),
    ("growth", "Rapid growth may mean internal chaos — offer simplicity"),
]


def _infer_objection_risk(lead: dict) -> str:
    title_lower = (lead.get("title") or "").lower()
    company = (lead.get("company") or "").lower()
    industry = (lead.get("company_industry") or "").lower()

    for keyword, objection in _OBJECTION_PATTERNS:
        if keyword in title_lower:
            return objection

    if any(w in company for w in ["enterprise", "global", "international"]):
        return "Large organization — may have existing vendor relationships"
    if any(w in industry for w in ["startup", "small"]):
        return "Small operation — budget may be limited"
    return "Standard outreach risk — ensure message differentiates clearly"


# ---------------------------------------------------------------------------
# Decision authority heuristics
# ---------------------------------------------------------------------------

_HIGH_AUTHORITY_TITLES = [
    "ceo", "chief", "owner", "founder", "president", "partner",
    "vp", "vice president", "head of", "director",
]

_MEDIUM_AUTHORITY_TITLES = [
    "manager", "lead", "senior", "principal", "lead",
]


def _summarize_authority(lead: dict) -> str:
    title_lower = (lead.get("title") or "").lower()
    authority = lead.get("buying_authority", 0)

    for high in _HIGH_AUTHORITY_TITLES:
        if high in title_lower:
            return f"Holds '{lead.get('title')}' role ({authority}/100 authority) — has significant decision-making power for this type of purchase"
    for med in _MEDIUM_AUTHORITY_TITLES:
        if med in title_lower:
            return f"Holds '{lead.get('title')}' role ({authority}/100 authority) — may need internal approval but is a key influencer"

    if authority >= 70:
        return f"Role '{lead.get('title')}' with {authority}/100 authority score — likely involved in decision process"
    return f"Role '{lead.get('title')}' with {authority}/100 authority score — may require engaging additional stakeholders"


# ---------------------------------------------------------------------------
# Business need heuristics
# ---------------------------------------------------------------------------


def _estimate_business_need(lead: dict) -> str:
    pain_points = lead.get("pain_points") or []
    industry = (lead.get("company_industry") or "").strip()
    growth = (lead.get("company_growth_stage") or "").strip()

    if pain_points:
        top = pain_points[0]
        if growth:
            return f"At {growth} stage, the primary need is addressing '{top}', which is critical for sustaining growth in the {industry} sector"
        return f"The primary business need is addressing '{top}' in the {industry} space"

    if growth:
        return f"Company is in {growth} phase — likely needs solutions that support scaling in {industry}"
    return f"Standard need for {industry} companies — improving operational efficiency and growth"


# ---------------------------------------------------------------------------
# Why-selected reasons
# ---------------------------------------------------------------------------


def _build_why_selected(lead: dict, enrichment: dict | None) -> list[str]:
    reasons: list[str] = []
    title = (lead.get("title") or "").strip()
    company = (lead.get("company") or "").strip()
    industry = (lead.get("company_industry") or "").strip()
    score_breakdown = lead.get("commercial_score_breakdown") or {}
    highlights = score_breakdown.get("highlights") or []
    buyer_score = score_breakdown.get("buyer_score", 0)
    authority_score = score_breakdown.get("authority_score", 0)

    if highlights:
        for h in highlights[:3]:
            reasons.append(f"Qualification: {h}")

    if title or company:
        role_desc = f"'{title}'" if title else ""
        company_desc = f" at {company}" if company else ""
        reasons.append(f"Role match: {role_desc}{company_desc} fits the target ICP")

    if buyer_score > 0:
        reasons.append(f"Strong buyer fit (score: {buyer_score}) — title aligns with decision-maker profile")

    if authority_score > 0:
        reasons.append(f"Decision authority (score: {authority_score}) — role has purchasing influence")

    pain_points = lead.get("pain_points") or []
    if pain_points:
        reasons.append(f"Relevant pain: {pain_points[0]}")

    buying_signals = lead.get("buying_signals") or []
    if buying_signals:
        reasons.append(f"Buying signal: {buying_signals[0]}")

    if industry:
        reasons.append(f"Industry alignment: operates in {industry}")

    # Deduplicate and limit
    seen: set[str] = set()
    unique: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique[:5]


# ---------------------------------------------------------------------------
# Pitch recommendation
# ---------------------------------------------------------------------------


def _recommend_pitch(lead: dict, enrichment: dict | None) -> str:
    pain_points = lead.get("pain_points") or []
    title = (lead.get("title") or "").strip()
    industry = (lead.get("company_industry") or "").strip()
    company = (lead.get("company") or "").strip()

    if pain_points:
        top_pain = pain_points[0]
        if title:
            return f"Position your solution as a way for {title} at {company or 'their company'} to solve '{top_pain}' in the {industry or 'current'} market"
        return f"Lead with how your solution directly addresses '{top_pain}', a critical challenge for {company or industry or 'this company'}"

    if industry:
        return f"Present your solution as a growth enabler for {company or 'companies'} in the {industry} sector"
    return f"Position as a way to help {company or 'this company'} modernize operations and drive growth"


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _build_summary(lead: dict, enrichment: dict | None, intelligence: dict) -> str:
    name = (lead.get("name") or "This lead").split()[0]
    company = (lead.get("company") or "").strip()
    title = (lead.get("title") or "").strip()
    industry = (lead.get("company_industry") or "").strip()
    score = intelligence.get("fit_score", 0)
    stage = intelligence.get("buying_stage", "awareness")
    urgency = intelligence.get("urgency", "low")
    authority = lead.get("buying_authority", 0)

    parts = [f"{name} ({title} at {company or 'unknown company'})"]
    if industry:
        parts.append(f"in {industry}")
    parts.append(f"fit score {score}/100")
    parts.append(f"at {stage} stage ({urgency} urgency)")
    parts.append(f"authority {authority}/100")

    pain_points = lead.get("pain_points") or []
    if pain_points:
        parts.append(f"pain: '{pain_points[0]}'")

    signals = lead.get("buying_signals") or []
    if signals:
        parts.append(f"signal: {signals[0].lower()}")

    return " | ".join(parts) + "."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_lead_intelligence(
    lead: dict,
    enrichment: dict | None = None,
) -> dict:
    """Generate structured sales intelligence for a single lead.

    All logic is deterministic — no LLM calls. Uses data already present
    in the canonical lead dict (pain_points, buying_signals, growth_stage,
    commercial_score_breakdown) and the optional enrichment dict.

    Args:
        lead: Canonical lead dict (may include commercial_score_breakdown
              from commercial_qualifier.py)
        enrichment: Optional canonical enrichment dict from the enricher layer

    Returns:
        Canonical lead intelligence dict with all fields described below.
    """
    score_breakdown = lead.get("commercial_score_breakdown") or {}

    # Normalize commercial score to 0-100 fit score
    raw_score = lead.get("commercial_score", score_breakdown.get("final_score", 50))
    fit_score = min(int(raw_score * 100 / 150), 100)
    if fit_score < 0:
        fit_score = 0

    # Confidence from enrichment if available, else estimate
    confidence = 0
    if enrichment and enrichment.get("confidence_score"):
        confidence = enrichment["confidence_score"]
    elif score_breakdown:
        confidence = fit_score

    decision_authority_summary = _summarize_authority(lead)
    buying_stage = _infer_buying_stage(lead, enrichment)
    urgency = _infer_urgency(lead, enrichment)
    estimated_business_need = _estimate_business_need(lead)
    objection_risk = _infer_objection_risk(lead)
    why_selected = _build_why_selected(lead, enrichment)
    recommended_pitch = _recommend_pitch(lead, enrichment)

    intelligence = {
        "fit_score": fit_score,
        "confidence": confidence,
        "why_selected": why_selected,
        "recommended_pitch": recommended_pitch,
        "decision_authority_summary": decision_authority_summary,
        "buying_stage": buying_stage,
        "urgency": urgency,
        "estimated_business_need": estimated_business_need,
        "objection_risk": objection_risk,
        "best_contact_reason": _best_contact_reason(lead, score_breakdown),
        "summary": "",
    }
    intelligence["summary"] = _build_summary(lead, enrichment, intelligence)

    return intelligence


def _best_contact_reason(lead: dict, score_breakdown: dict) -> str:
    title = (lead.get("title") or "").strip()
    company = (lead.get("company") or "").strip()
    buyer_score = score_breakdown.get("buyer_score", 0)
    authority_score = score_breakdown.get("authority_score", 0)

    if buyer_score >= 30 and authority_score >= 20:
        return f"'{title}' at {company} combines strong buyer fit ({buyer_score}) with high authority ({authority_score}) — best positioned to act on your outreach"
    if buyer_score >= 20:
        return f"'{title}' is a strong buyer profile match and is the right contact to start the conversation"
    if authority_score >= 15:
        return f"'{title}' has decision authority at {company} — a good entry point for engagement"
    return f"'{title}' at {company} is a relevant contact based on role and industry alignment"
