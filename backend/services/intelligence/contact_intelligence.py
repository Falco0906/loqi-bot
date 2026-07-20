DECISION_AUTHORITY_TITLES: dict[str, list[str]] = {
    "c_level": [
        "ceo", "cfo", "cto", "coo", "cmo", "cio", "chief",
        "president", "owner", "founder", "partner",
    ],
    "vp_director": [
        "vp", "svp", "evp", "avp", "director", "head of",
        "vice president",
    ],
    "manager": [
        "manager", "lead", "supervisor", "team lead",
    ],
    "individual_contributor": [
        "engineer", "developer", "analyst", "associate",
        "specialist", "coordinator", "representative",
    ],
}

ROLE_RELEVANCE: dict[str, list[str]] = {
    "high": [
        "sales", "revenue", "growth", "business development",
        "partnerships", "marketing", "product",
    ],
    "medium": [
        "operations", "strategy", "finance", "engineering",
        "technology", "it",
    ],
    "low": [
        "hr", "legal", "compliance", "support",
        "customer success", "admin",
    ],
}


def generate_contact_intelligence(
    contact: dict,
    enrichment: dict | None = None,
) -> dict:
    title = (contact.get("title") or "").lower()
    role = (enrichment or {}).get("role", "")
    decision_authority = _classify_decision_authority(title)
    relevance_score = _score_role_relevance(title, role)
    return {
        "decision_authority": decision_authority,
        "relevance_score": relevance_score,
        "title_normalized": title,
        "summary": _build_contact_summary(title, decision_authority, relevance_score),
    }


def _classify_decision_authority(title: str) -> str:
    if not title:
        return "unknown"
    for authority, keywords in DECISION_AUTHORITY_TITLES.items():
        if any(kw in title for kw in keywords):
            return authority
    return "unknown"


def _score_role_relevance(title: str, role: str) -> str:
    combined = f"{title} {role}".lower()
    for relevance, keywords in ROLE_RELEVANCE.items():
        if any(kw in combined for kw in keywords):
            return relevance
    if title:
        return "low"
    return "unknown"


def _build_contact_summary(
    title: str, decision_authority: str, relevance_score: str,
) -> str:
    authority_label = decision_authority.replace("_", " ").title()
    relevance_label = relevance_score.title()
    return f"{title or 'Unknown Title'} ({authority_label}, Relevance: {relevance_label})"
