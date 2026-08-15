"""Discovery Plan — the structured intelligence item behind every search.

The raw campaign objective is NEVER handed to a search provider. Instead,
``derive_discovery_plan`` turns the objective into a complete structured plan:

- offering / primary_services: the short product/service noun phrases
- target_audience, industries, sub_industries
- icp_summary, buyer_personas, decision_maker_roles
- company_keywords: buyer-focused keyword combos (never the raw sentence)
- negative_keywords: company types to EXCLUDE from retrieval
- pain_points, buying_signals: market tension to look for
- technologies, business_characteristics: observed company attributes
- exclusions, geography, company_size: retrieval constraints
- messaging_angle, success_criteria: strategy-facing intent

The plan is persisted on the discovery (``discoveries.metadata.plan``) and is
the ONLY thing the provider pipeline (``lead_provider.search_with_expansion``,
``search_expansion.expand_search_intent``, providers) consumes. The campaign
objective itself is reserved for strategy generation.

Derivation is deterministic wherever possible; the LLM is used ONCE, inside
the canonical ICP extractor, purely for semantic extraction (buyer roles /
industries / keywords). Every semantic field degrades to a deterministic
table — a plan always exists even without an AI key.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field


class DiscoveryPlan(BaseModel):
    offering: str = ""
    primary_services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    industries: list[str] = Field(default_factory=list)
    sub_industries: list[str] = Field(default_factory=list)
    icp_summary: str = ""
    buyer_personas: list[str] = Field(default_factory=list)
    company_keywords: list[str] = Field(default_factory=list)
    decision_maker_roles: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    business_characteristics: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    company_size: list[str] = Field(default_factory=list)
    messaging_angle: str = ""
    success_criteria: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()


def _log(msg: str) -> None:
    print(f"[discovery_plan] {msg}")


def _dedupe(items: list) -> list:
    seen = set()
    result = []
    for item in items or []:
        key = " ".join(str(item).strip().lower().split())
        if key and key not in seen:
            seen.add(key)
            result.append(str(item).strip())
    return result


def _split_intent(query: str) -> tuple[str, str]:
    """Split 'offering [for/to/in/targeting] buyer' into (offering, buyer).

    The first splitter wins (targets may also contain 'in'). Returns
    (query, "") when no separator exists.
    """
    low = query.lower()
    for sep in (" targeting ", " for ", " to ", " in "):
        idx = low.find(sep)
        if idx > 0:
            service = query[:idx].strip()
            target = query[idx + len(sep):].strip()
            if service and target:
                return service, target
    return query.strip(), ""


_GEO_KEYWORDS = {
    "United States": ["usa", "united states", "us market", "american", "california", "new york", "texas", "florida", "illinois", "northeast", "midwest", " in the us", "based in the us"],
    "United Kingdom": ["uk", "united kingdom", "britain", "england", "scotland", "london"],
    "Germany": ["germany", "german", "berlin", "munich", "frankfurt", "bavaria"],
    "France": ["france", "french", "paris"],
    "Canada": ["canada", "canadian", "toronto", "vancouver"],
    "Australia": ["australia", "australian", "sydney", "melbourne"],
    "Singapore": ["singapore"],
    "UAE": ["uae", "dubai", "abudhabi", "united arab emirates"],
    "Europe": ["europe", "european", "eu", "europe-wide"],
}


def _infer_geography(text: str) -> list[str]:
    low = (text or "").lower()
    found = []
    for region, keywords in _GEO_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(kw)}\b", low) for kw in keywords):
            found.append(region)
    return _dedupe(found)


_SIZE_KEYWORDS = [
    ("enterprise", ["enterprise", "fortune 500", "large company", "large enterprises", "big business"]),
    ("mid-market", ["mid market", "mid-market", "midmarket", "established company"]),
    ("smb", ["smb", "small and medium", "small companies", "small firm"]),
    ("startups", ["startup", "startups", "start up", "early stage", "venture backed", "series a", "series b", "funded"]),
]


def _infer_company_size(text: str) -> list[str]:
    low = (text or "").lower()
    found = []
    for size, keywords in _SIZE_KEYWORDS:
        if any(re.search(rf"\b{re.escape(kw)}\b", low) for kw in keywords):
            found.append(size)
    return _dedupe(found)


# ── Semantics per buyer industry (deterministic fallbacks) ──────────────
# Each profile feeds pain points, buying signals, likely tech stack,
# business characteristics, and negative (exclude) terms for discovery.
# Broken-backed words are avoided; these strings go straight to providers.

_INDUSTRY_PROFILES = {
    "restaurants": {
        "pain_points": ["No online ordering experience", "Missed calls and lost reservations", "Manual and error-prone booking", "No-shows eating margins", "Inconsistent follow-up with regulars", "Fragile staffing during peak times"],
        "signals": ["Recently opened location", "Hiring front-of-house staff", "Outdated website", "No online ordering", "Low review scores", "Expanded to a new location"],
        "technologies": ["Toast POS", "Square", "Clover", "OpenTable", "Resy", "Instagram ordering", "DoorDash"],
        "characteristics": ["independent", "single or few locations", "owner-operated"],
        "negative_terms": ["hotel", "resort", "nightclub", "franchise chain", "enterprise chain", "corporate cafeteria"],
    },
    "dental": {
        "pain_points": ["Missed appointments and no-shows", "Manual reminders and follow-up", "Unused capacity in the schedule", "Thin front-desk bandwidth", "Outdated patient outreach"],
        "signals": ["Hiring front-desk staff", "New patient acquisition push", "Outdated website", "Low online reviews", "Expanded hours or second location"],
        "technologies": ["Practice management software", "Dentrix", "Open Dental", "Zocdoc", "Insurance clearing", "Recall automation"],
        "characteristics": ["independently owned", "single practice", "family-owned"],
        "negative_terms": ["corporate DSO chain", "franchise network", "hospital"],
    },
    "healthcare": {
        "pain_points": ["Manual scheduling and reminders", "No-show-driven revenue loss", "Front-office overload", "Uncoordinated patient communication", "Weak online booking"],
        "signals": ["Hiring admin staff", "New location announced", "Outdated website", "Launching online bookings"],
        "technologies": ["Practice management software", "EHR", "Patient portal", "Zocdoc", "SMS campaigns"],
        "characteristics": ["independent clinic", "small group practice"],
        "negative_terms": ["hospital system", "health system", "big corporate network"],
    },
    "wellness": {
        "pain_points": ["Manual booking and class scheduling", "No-shows from weak reminders", "Member and client retention", "Slow follow-up with inquiries", "Time-absorbing bookkeeping"],
        "signals": ["Recently opened", "Hiring staff", "Expanding service list", "Outdated website", "No online booking widget"],
        "technologies": ["Scheduling software", "Square", "Instagram", "Email marketing"],
        "characteristics": ["independent studio", "owner-operated", "single location"],
        "negative_terms": ["national chain", "franchise network", "hotel spa", "enterprise gym"],
    },
    "gym": {
        "pain_points": ["Member churn and attrition", "Manual member tracking", "No automated check-ins", "Slow lead follow-up", "Underused sessions"],
        "signals": ["Advertising a new location", "Hiring trainers", "Outdated website", "No online member portal"],
        "technologies": ["Gym management software", "Booking software", "Square", "Instagram", "Email marketing"],
        "characteristics": ["independently owned", "single or few locations", "boutique"],
        "negative_terms": ["national chain", "franchise network", "corporate wellness"],
    },
    "legal": {
        "pain_points": ["Call-dependent intake", "Manual case tracking", "Slow client follow-up", "Overloaded paralegals"],
        "signals": ["Hiring intake staff", "Expanding practice areas", "Outdated website", "Investing in marketing"],
        "technologies": ["Practice management software", "e-signature", "Case intake CRM", "Google Ads"],
        "characteristics": ["independent firm", "small partnership"],
        "negative_terms": ["national firm", "big-law", "franchise", "insurance defense mill"],
    },
    "real_estate": {
        "pain_points": ["Slow lead response times", "Manual listing follow-ups", "Work scattered across tools", "Thin commission margins"],
        "signals": ["Expanding agent teams", "Running paid campaigns", "Outdated website", "New branches"],
        "technologies": ["Real estate CRM", "Listing platforms", "Open house tools", "Follow-up automation"],
        "characteristics": ["independent agents", "boutique brokerage", "single-office"],
        "negative_terms": ["bank", "developer conglomerate", "huge national chain", "multinational"],
    },
    "finance": {
        "pain_points": ["Manual client follow-up", "Admin-heavy onboarding", "Low-intent inbounds", "Compliance burden on outreach"],
        "signals": ["Hiring advisors", "Digital marketing push", "Adopting fintech tools", "New growth office"],
        "technologies": ["CRM", "Spreadsheets", "Digital documents", "Compliance software"],
        "characteristics": ["regional", "independent advisory", "specialist firm"],
        "negative_terms": ["universal bank", "global bank", "huge institutional", "central bank"],
    },
    "startups": {
        "pain_points": ["Tiny team, low bandwidth", "Founder doing everything", "Undefined outbound motion", "No repeatable lead flow"],
        "signals": ["Hiring go-to-market", "Raised a round", "Launched a new product", "Changing websites"],
        "technologies": ["CRM", "Playbooks", "LinkedIn", "AI tools"],
        "characteristics": ["founder-led", "seed-to-B", "venture-backed"],
        "negative_terms": ["huge corp", "enterprise conglomerate"],
    },
    "saas": {
        "pain_points": ["Spreadsheet-led ops", "Slow sales follow-up", "Unstructured pipeline", "No consistent outbound motion"],
        "signals": ["Hiring sales staff", "Series A/B funding", "Rebuilding website", "Adopting new tooling"],
        "technologies": ["CRM", "Sales outreach", "Reply automation", "Product analytics"],
        "characteristics": ["founder-led", "seed-to-B", "product-first"],
        "negative_terms": ["big enterprise conglomerate", "outsourcer"],
    },
    "tech": {
        "pain_points": ["Resource-heavy engineering", "Slow procurement", "Tool sprawl", "Competing priorities"],
        "signals": ["Engineering hiring", "New tool adoption", "Modernization pushes"],
        "technologies": ["Observability", "DevOps tooling", "CRM", "Publish-subscribe"],
        "characteristics": ["growth-stage", "product companies", "technical buyers"],
        "negative_terms": ["diversified conglomerate", "enterprise"],
    },
    "education": {
        "pain_points": ["Administrative gaps", "Manual enrollment follow-up", "Political volunteer overload", "Parent communication overload"],
        "signals": ["Enrollment seasons", "New campus", "Building a website", "Hiring admissions"],
        "technologies": ["Student information system", "CRM", "Email automation", "Website"],
        "characteristics": ["private school", "training center", "college"],
        "negative_terms": ["government", "system-wide chain"],
    },
    "retail": {
        "pain_points": ["Sparse ecommerce presence", "Manual order ops", "Broad outreach", "Discount-driven only"],
        "signals": ["Hiring marketing", "Opening online store", "Rebuilding brand", "Expansion"],
        "technologies": ["Shopify", "Square", "Instagram", "Email marketing"],
        "characteristics": ["independently owned", "boutiques", "family-run"],
        "negative_terms": ["big box chain", "discount giant", "national retailer"],
    },
    "construction": {
        "pain_points": ["Manual estimates", "Slow bid follow-up", "Field and admin mismatch", "Project-driven communication"],
        "signals": ["Expanding to new projects", "Hiring project managers", "Modernizing the office"],
        "tech_stacks": ["Estimation software", "Project tools", "CRM"],
        "characteristics": ["owner-operator", "small contractor", "regional builder"],
        "negative_terms": ["national developer", "industrial giant", "government entity"],
    },
    "manufacturing": {
        "pain_points": ["Manual order intake", "Slow quote follow-up", "Paper-to-digital gaps", "Distributed shops"],
        "signals": ["Investing in a new line", "Hiring operations leadership", "Digitizing shop ops"],
        "technologies": ["ERP", "CM tooling", "MES", "CAD stack"],
        "characteristics": ["job-shop", "small OEM", "regional producer"],
        "negative_terms": ["global conglomerate", "large multinational"],
    },
    "consulting": {
        "pain_points": ["Referral-dependent pipeline", "Manual proposal work", "Inconsistent growth", "No outreach motion"],
        "signals": ["Hiring delivery roles", "Building website", "Partner expansion", "Publishing thought leadership"],
        "technologies": ["CRM", "LinkedIn", "Proposal tools"],
        "characteristics": ["boutique", "independent consultancy", "specialist"],
        "negative_terms": ["big four", "global consultancy", "enterprise"],
    },
    "logistics": {
        "pain_points": ["Manual coordination", "Fragmented tracking", "Driver-admin overhead", "Slow quote turns"],
        "signals": ["Investing in route software", "Hiring dispatchers", "Digital quoting"],
        "technologies": ["Fleet management", "TMS", "ELD software"],
        "characteristics": ["regional carrier", "small fleet", "3PL boutique"],
        "negative_terms": ["global shipping giant", "national hub"],
    },
}

# Rolled-up negative terms used when a plan maps to every industry profile.
_NEGATIVE_FALLBACK = ["nightclub", "hotel", "franchise chain", "enterprise"]


_INDUSTRY_ALIASES = {
    "hospitality": "restaurants",
    "food service": "restaurants",
    "restaurant": "restaurants",
    "cafe": "restaurants",
    "cafes": "restaurants",
    "coffee shop": "restaurants",
    "coffee shops": "restaurants",
    "gym": "gym",
    "fitness center": "gym",
    "dental": "dental",
    "startups": "startups",
    "saas": "saas",
    "healthcare": "healthcare",
    "health": "healthcare",
    "wellness": "wellness",
    "legal": "legal",
    "law": "legal",
    "law firm": "legal",
    "real estate": "real_estate",
    "finance": "finance",
    "accounting": "finance",
    "tech": "tech",
    "software": "tech",
    "education": "education",
    "retail": "retail",
    "construction": "construction",
    "manufacturing": "manufacturing",
    "consulting": "consulting",
    "logistics": "logistics",
}

_TRIGGERS = {
    "pain": {
        "hiring": ["Hiring or team strain"],
        "hero": ["Outdated or weak website"],
        "booking": ["Manual booking and no-shows"],
        "reservations": ["Missed reservations"],
        "online ordering": ["No online ordering"],
        "review": ["Low review scores"],
        "orders": ["Manual order flow and errors"],
        "call": ["Missed calls", "Phone-dependent workflow"],
    },
    "signal": {
        "new": ["Recently opened"],
        "hiring": ["Hiring activity"],
        "booking": ["No online booking"],
        "funding": ["Recent funding"],
        "expansion": ["Location expansion"],
        "review": ["Low review score"],
    },
}


def _match_triggers(text: str, kind: str) -> list[str]:
    low = (text or "").lower()
    found = []
    for word, phrases in _TRIGGERS.get(kind, {}).items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            found.extend(phrases)
    return _dedupe(found)


def _profile_for(industries: list[str]) -> dict:
    """Best single profile for the plan's leading industries."""
    for ind in industries:
        key = _INDUSTRY_ALIASES.get(ind.lower().strip(), ind.lower().strip())
        profile = _INDUSTRY_PROFILES.get(key)
        if profile:
            return profile
    return {}


_SERVICE_TITLES = {
    "website": "Website Development",
    "websites": "Website Development",
    "web design": "Website Design",
    "crm": "CRM",
    "marketing": "Marketing",
    "seo": "SEO",
    "automation": "Automation",
    "automations": "Automation",
    "bookkeeping": "Bookkeeping",
    "accounting": "Accounting",
    "scheduling": "Online Booking",
    "calling": "AI Calling",
    "phone": "AI Calling",
    "ai": "AI",
    "ai solution": "AI Automation",
    "ai automations": "AI Automation",
    "ai automation": "AI Automation",
    "pos": "Point of Sale",
    "video": "Video Production",
    "security": "Security",
    "cleaning": "Cleaning Services",
}


def _infer_primary_services(offering: str) -> list[str]:
    """Split the offering into primary service noun phrases.

    'AI automations and websites' → ['AI Automation', 'Website Development'].
    """
    if not offering:
        return []
    parts = re.split(r"\s*(?:,| and | & | \+ | slash )\s*", offering, flags=re.I)
    cleaned = []
    for part in parts:
        part = " ".join(part.strip().split())
        if part and part not in cleaned:
            cleaned.append(part)
    out = []
    for part in cleaned:
        key = re.sub(r"\s+", " ", part.lower())
        out.append(_SERVICE_TITLES.get(key, part.title()))
    return _dedupe(out)


def _build_icp_summary(offering: str, industries: list[str], roles: list[str]) -> str:
    pieces = []
    if offering:
        pieces.append(f"Companies buying {offering}")
    if industries:
        pieces.append("in " + ", ".join(industries[:3]))
    if roles:
        pieces.append("whose decision makers are " + ", ".join(roles[:3]))
    return " ".join(pieces) + "." if pieces else ""


def _build_messaging_angle(offering: str, industries: list[str], pain_points: list[str]) -> str:
    pain = pain_points[0] if pain_points else "day-to-day operations"
    industry = industries[0] if industries else "their market"
    if offering:
        angle = (
            f"Lead with the outcome {offering} delivers to {industry} businesses — "
            f"directly off the back of {pain.lower()}. Position the fix, not the feature."
        )
    else:
        angle = f"Lead {industry} operators toward {pain.lower()} — position the fix, not the feature."
    return angle


def _build_success_criteria(roles: list[str], industries: list[str]) -> str:
    target = (roles[0] if roles else "") or (industries[0] if industries else "targets")
    return (
        f"Land scheduled conversations with {target} decision makers; "
        "key milestone is a real reply with intent (call booked or CRM update), "
        "with reply-rate above the cold flat baseline for the vertical."
    )


def _build_company_keywords(roles: list[str], industries: list[str]) -> list[str]:
    """Buyer-focused keyword combos — never the raw objective sentence."""
    keywords = []
    for role in _dedupe(roles)[:6]:
        for ind in _dedupe(industries)[:3]:
            keywords.append(f"{role} {ind}")
    return _dedupe(keywords)[:12]


def _build_persona(roles: list[str], industries: list[str]) -> list[str]:
    """Compose decision-maker personas from roles + industries."""
    personas = []
    for role in _dedupe(roles)[:8]:
        for ind in _dedupe(industries)[:3]:
            personas.append(f"{role} ({ind})")
            if len(personas) >= 12:
                break
        if len(personas) >= 12:
            break
    return personas[:12]


def derive_discovery_plan(query: str, existing_context: Optional[dict] = None) -> DiscoveryPlan:
    """Derive the structured Discovery Plan from a raw free-text objective.

    The pull-step pushes every data point into the canonical plan. When no
    AI key is available (or extraction fails), deterministic fallbacks
    guarantee every field still exists.
    """
    query = (query or "").strip()
    if not query:
        return DiscoveryPlan()

    from services.icp_extractor import extract_structured_icp

    icp = extract_structured_icp(query, existing_context) or {}

    offering = str(icp.get("offer") or "").strip()
    target_audience = str(icp.get("target_audience") or "").strip() or str(icp.get("buyer_target_audience") or "").strip()
    if not offering:
        offering, target_audience = _split_intent(query)
    if not target_audience:
        _, target_audience = _split_intent(query)

    industries = _dedupe(icp.get("buyer_industries") or [])[:4]
    if not industries and target_audience:
        industries = _dedupe([target_audience])[:1]
    roles = _dedupe(icp.get("buyer_roles") or [])[:10]
    exclusions = _dedupe(icp.get("excluded_roles") or [])
    keywords = _dedupe((icp.get("keywords") or []) + (icp.get("search_hints") or []))[:12]
    if not keywords:
        keywords = _build_company_keywords(roles, industries)

    personas = _build_persona(roles, industries)
    if not personas:
        personas = [f"{r} (target)" for r in roles[:6]] or [f"{i} buyer" for i in industries[:6]]

    geography = _infer_geography(query)
    company_size = _infer_company_size(query)

    # Semantic fields (deterministic + profile-driven).
    profile = _profile_for(industries)
    pain_points = _dedupe(profile.get("pain_points") or [])[:6]
    if not pain_points:
        pain_points = _match_triggers(query, "pain") or ["Manual day-to-day operations", "Slow lead-by-lead follow-up"]
    buying_signals = _dedupe(profile.get("signals") or [])[:8]
    if not buying_signals:
        buying_signals = _match_triggers(query, "signal")[:8]
    technologies = _dedupe(profile.get("technologies") or [])[:8]
    characteristics = _dedupe(profile.get("characteristics") or [])[:6]
    negative_terms = _dedupe(profile.get("negative_terms") or [])[:8]
    if not negative_terms:
        negative_terms = _NEGATIVE_FALLBACK

    messaging_angle = _build_messaging_angle(offering, industries, pain_points)
    success_criteria = _build_success_criteria(roles, industries)

    plan = DiscoveryPlan(
        offering=offering,
        primary_services=_infer_primary_services(offering),
        target_audience=target_audience,
        industries=industries,
        sub_industries=industries[1:] if len(industries) > 1 else [],
        icp_summary=_build_icp_summary(offering, industries, roles),
        buyer_personas=personas,
        company_keywords=keywords,
        decision_maker_roles=roles,
        negative_keywords=negative_terms,
        pain_points=pain_points,
        buying_signals=buying_signals,
        technologies=technologies,
        business_characteristics=characteristics,
        exclusions=exclusions,
        geography=geography,
        company_size=company_size,
        messaging_angle=messaging_angle,
        success_criteria=success_criteria,
    )
    _log(
        f"derived plan: offering='{plan.offering}' services={plan.primary_services} "
        f"industries={plan.industries} roles={len(plan.decision_maker_roles)} "
        f"keywords={len(plan.company_keywords)} negatives={len(plan.negative_keywords)}"
    )
    return plan


def icp_from_plan(plan: dict) -> dict:
    """Rebuild the canonical buyer-intent ICP shape from a DiscoveryPlan.

    Uses the same keys the pipeline's own extractor emits, so the rest of
    the chain (expansion, qualification, filtering, providers) works
    unchanged — including negative keywords for exclusion.
    """
    plan = plan or {}
    roles = _dedupe(plan.get("decision_maker_roles") or [])[:10]
    industries = _dedupe(plan.get("industries") or [])[:4]
    return {
        "offer": str(plan.get("offering") or ""),
        "primary_services": _dedupe(plan.get("primary_services") or []),
        "service_category": "",
        "buyer_industries": industries,
        "buyer_roles": roles,
        "excluded_roles": _dedupe(plan.get("exclusions") or []),
        "negative_keywords": _dedupe(plan.get("negative_keywords") or []),
        "company_types": _dedupe(plan.get("company_size") or []),
        "pain_points": _dedupe(plan.get("pain_points") or [])[:8],
        "buying_signals": _dedupe(plan.get("buying_signals") or [])[:8],
        "technologies": _dedupe(plan.get("technologies") or [])[:8],
        "keywords": _dedupe(plan.get("company_keywords") or [])[:10],
        "search_hints": _dedupe(plan.get("buyer_personas") or [])[:6],
        "mode": "plan",
    }