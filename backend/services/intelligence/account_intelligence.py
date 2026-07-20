ACCOUNT_TIER_KEYWORDS: dict[str, list[str]] = {
    "enterprise": [
        "enterprise", "fortune", "global", "multinational",
        "10,000+", "10000+", "100000+",
    ],
    "mid_market": [
        "mid-market", "midmarket", "growing", "series", "expansion",
        "1,000+", "1000+", "5000+",
    ],
    "smb": [
        "startup", "small business", "sme", "emerging",
        "50+", "100+", "200+",
    ],
}

BUYING_INTENT_KEYWORDS: dict[str, list[str]] = {
    "high": [
        "hiring sales", "hiring vp", "looking for crm",
        "evaluating tools", "rfp", "request for proposal",
        "seeking solution", "implementing",
    ],
    "medium": [
        "growing team", "expanding", "new funding",
        "raised series", "new office",
    ],
    "low": [
        "restructuring", "downsizing", "layoffs",
        "budget cuts", "acquisition",
    ],
}


def generate_account_intelligence(
    company: dict,
    enrichment: dict | None = None,
) -> dict:
    name = company.get("name", "")
    domain = company.get("domain", "") or company.get("website", "")
    industry = company.get("industry", "")
    size = company.get("size", "") or (enrichment or {}).get("size", "")
    signals_text = _build_signals_text(company, enrichment)
    tier = _classify_account_tier(signals_text, size)
    buying_intent = _infer_buying_intent(signals_text)
    return {
        "account_tier": tier,
        "buying_intent": buying_intent,
        "industry": industry,
        "domain": domain,
        "company_name": name,
        "summary": _build_account_summary(name, tier, industry, buying_intent),
    }


def _build_signals_text(company: dict, enrichment: dict | None) -> str:
    parts = []
    parts.extend(company.get("buying_signals") or [])
    parts.extend(company.get("recent_events") or [])
    parts.append(company.get("company_growth_stage", ""))
    if enrichment:
        parts.append(enrichment.get("description", ""))
        parts.append(enrichment.get("recent_news", ""))
    return " ".join(parts).lower()


def _classify_account_tier(signals_text: str, size: str) -> str:
    for tier, keywords in ACCOUNT_TIER_KEYWORDS.items():
        if any(kw in signals_text for kw in keywords):
            return tier
    try:
        num = int(size.replace(",", "").replace("+", ""))
        if num >= 10000:
            return "enterprise"
        if num >= 1000:
            return "mid_market"
        return "smb"
    except (ValueError, AttributeError):
        pass
    if signals_text:
        return "smb"
    return "unknown"


def _infer_buying_intent(signals_text: str) -> str:
    for intent, keywords in BUYING_INTENT_KEYWORDS.items():
        if any(kw in signals_text for kw in keywords):
            return intent
    if not signals_text:
        return "unknown"
    return "low"


def _build_account_summary(
    name: str, tier: str, industry: str, buying_intent: str,
) -> str:
    parts = [name or "Unknown", f"({tier.replace('_', ' ').title()})"]
    if industry:
        parts.append(f"in {industry}")
    parts.append(f"- Buying intent: {buying_intent}")
    return " ".join(parts)
