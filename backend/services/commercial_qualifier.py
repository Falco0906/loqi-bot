import re
from typing import Optional


def _log(message: str) -> None:
    print(f"[commercial_qualifier] {message}")


EXCLUDED_COMPANY_PATTERNS = [
    r"\bagency\b",
    r"\bconsulting\b",
    r"\bsolutions\b",
    r"\bservices\b",
    r"\bdigital\b",
    r"\bmedia\b",
    r"\bmarketing\b",
    r"\bcreative\b",
    r"\bsoftware\b",
    r"\btechnology\b",
    r"\btech\b",
    r"\bdev(elopment)?\b",
    r"\bdesign\b",
    r"\bweb\b",
    r"\bapp\b",
    r"\bplatform\b",
    r"\bautomated?\b",
    r"\bautomation\b",
    r"\bai\s+(solutions|services|tools|software|platform)\b",
    r"\bhospitality\s+(tech|saas|software|solutions)\b",
    r"\brestaurant\s+(tech|saas|software|vendors)\b",
    r"\bfood\s+(tech|software|solutions)\b",
    r"\bcloud\b",
    r"\bcloud-based\b",
    r"\bsaas\b",
    r"\bplatform\b",
    r"\binc\b",
    r"\bllc\b",
    r"\bltd\b",
    r"\bcorp(orate)?\b",
]

EXCLUDED_TITLE_PATTERNS = [
    r"\bdev(eloper)?\b",
    r"\bdesign(er)?\b",
    r"\bfreelance\b",
    r"\bfreelancer\b",
    r"\bcontract(or)?\b",
    r"\bconsult(ant|ing)?\b",
    r"\badvisor\b",
    r"\bagency\b",
    r"\bseo\b",
    r"\bmarketing\b.*\bspecialist\b",
    r"\bspecialist\b.*\bmarket\b",
    r"\bwriter\b",
    r"\bcopywriter\b",
    r"\bblogger\b",
    r"\binfluencer\b",
    r"\bcoach\b",
    r"\btrainer\b",
    r"\bmentor\b",
    r"\bvirtual\s+assistant\b",
    r"\bva\b",
    r"\brecruiter\b",
    r"\bstaffing\b",
    r"\baccount\s+manager\b",
    r"\bsales\s+rep\b",
    r"\baccount\s+exec(utive)?\b",
    r"\bsdr\b",
    r"\bbdr\b",
    r"\blapse\b",
]

VENDOR_INDICATORS = [
    "agency",
    "consulting",
    "solutions",
    "services",
    "digital",
    "marketing",
    "creative",
    "software",
    "technology",
    "tech",
    "dev",
    "design",
    "web",
    "app",
    "platform",
    "automated",
    "automation",
    "ai",
    "saas",
    "cloud",
    "vendor",
    "provider",
    "integrator",
    "implementation",
]

BUYER_TITLE_KEYWORDS = [
    "owner",
    "founder",
    "co-founder",
    "co owner",
    "founder &",
    "founder of",
    "entrepreneur",
]

LEADERSHIP_TITLE_KEYWORDS = [
    "ceo",
    "coo",
    "cfo",
    "cto",
    "president",
    "vp",
    "vice president",
    "director",
    "head of",
    "chief",
    "partner",
    "managing",
]

OPERATIONS_TITLE_KEYWORDS = [
    "general manager",
    "operations manager",
    "operations director",
    "manager",
    "gm",
    "franchise",
    "multi-unit",
    "multi location",
    "regional",
    "district",
]

HOSPITALITY_KEYWORDS = [
    "restaurant",
    "hospitality",
    "hotel",
    "resort",
    "food",
    "dining",
    "cafe",
    "bistro",
    "eatery",
    "grill",
    "bar",
    "pub",
    "club",
    "catering",
]

CHAIN_INDICATORS = [
    "group",
    "holdings",
    "partners",
    "corp",
    "corp.",
    "company",
    "llc",
    "inc",
    "inc.",
    "franchise",
    "chain",
    "brands",
]


def score_lead(lead: dict, icp: dict) -> dict:
    """
    Commercial qualification scoring for a single lead.

    Returns a detailed scoring result with breakdown.
    """
    title = (lead.get("title") or "").strip()
    name = (lead.get("name") or "").strip()
    company = (lead.get("company") or "").strip()
    linkedin_url = (lead.get("linkedin_url") or "").strip()

    breakdown = {
        "lead_name": name,
        "lead_title": title,
        "lead_company": company,
        "buyer_score": 0,
        "company_score": 0,
        "authority_score": 0,
        "relevance_score": 0,
        "drift_penalty": 0,
        "final_score": 0,
        "excluded": False,
        "excluded_reason": "",
        "highlights": [],
        "penalties": [],
        "drift_flags": [],
    }

    title_lower = title.lower()
    company_lower = company.lower()
    name_lower = name.lower()

    if _is_junk_entity(name, title, company):
        breakdown["excluded"] = True
        breakdown["excluded_reason"] = "junk_entity"
        breakdown["penalties"].append("rejected: junk entity detected")
        _log(f"[EXCLUDED] {name} @ {company} — junk entity")
        return breakdown

    excluded_company, company_reason = _check_excluded_company(company_lower, title_lower)
    if excluded_company:
        breakdown["excluded"] = True
        breakdown["excluded_reason"] = company_reason
        breakdown["drift_penalty"] = -100
        breakdown["penalties"].append(f"excluded: {company_reason}")
        breakdown["drift_flags"].append("company is vendor/service provider")
        _log(f"[EXCLUDED] {name} @ {company} — {company_reason}")
        return breakdown

    vendor_title, vendor_reason = _check_vendor_title(title_lower)
    if vendor_title:
        breakdown["drift_penalty"] -= 60
        breakdown["penalties"].append(f"vendor_title: {vendor_reason}")
        breakdown["drift_flags"].append(f"title is vendor/provider: {vendor_reason}")
        breakdown["highlights"].append(f"DRIFT WARNING: title indicates vendor ({vendor_reason})")
        _log(f"[DRIFT PENALTY] {name} @ {company} — vendor title: {vendor_reason}")

    buyer_score = _score_buyer_fit(title_lower, company_lower)
    breakdown["buyer_score"] = buyer_score
    if buyer_score > 0:
        breakdown["highlights"].append(f"buyer_fit: +{buyer_score}")
        _log(f"[BUYER SCORE] {name}: {buyer_score}")
    else:
        breakdown["penalties"].append(f"poor_buyer_fit: {buyer_score}")

    company_score = _score_company_quality(company_lower, title_lower)
    breakdown["company_score"] = company_score
    if company_score > 0:
        breakdown["highlights"].append(f"company_quality: +{company_score}")
        _log(f"[COMPANY SCORE] {name} @ {company}: {company_score}")
    elif company_score < 0:
        breakdown["penalties"].append(f"poor_company: {company_score}")

    authority_score = _score_authority(title_lower)
    breakdown["authority_score"] = authority_score
    if authority_score > 0:
        breakdown["highlights"].append(f"authority: +{authority_score}")

    relevance_score = _score_relevance(title_lower, company_lower, icp)
    breakdown["relevance_score"] = relevance_score
    if relevance_score > 0:
        breakdown["highlights"].append(f"icp_relevance: +{relevance_score}")

    drift_penalty = breakdown["drift_penalty"]

    final_score = max(0, buyer_score + company_score + authority_score + relevance_score + drift_penalty)
    breakdown["final_score"] = final_score

    if breakdown["highlights"]:
        _log(f"[SCORED] {name} @ {company} = {final_score} ({', '.join(breakdown['highlights'])})")
    if breakdown["penalties"]:
        _log(f"[PENALTIES] {name}: {breakdown['penalties']}")
    if breakdown["drift_flags"]:
        _log(f"[DRIFT] {name}: {breakdown['drift_flags']}")

    return breakdown


def _is_junk_entity(name: str, title: str, company: str) -> bool:
    """Detect malformed/junk entities that should be rejected."""
    name_lower = name.lower()
    title_lower = title.lower()
    company_lower = company.lower()

    if not name or len(name.strip()) < 2:
        return True

    junk_name_patterns = [
        r"^actually\s",
        r"^the\s",
        r"^\d+\s",
        r"^\-",
        r"^linkedin",
        r"profile$",
        r"^view\s",
        r"^my\s",
    ]
    for pattern in junk_name_patterns:
        if re.search(pattern, name_lower):
            return True

    if name_lower in ["unknown", "none", "n/a", "na", ".", "-", ""]:
        return True

    if company_lower in ["unknown", "unknown company", "none", "n/a", "", "linkedin"]:
        return True

    if not title or len(title.strip()) < 2:
        return True

    if "..." in name or "..." in company:
        return True

    if len(name) > 80 or len(title) > 100:
        return True

    placeholder_patterns = [
        r"placeholder",
        r"test\s*account",
        r"sample\s*user",
        r"example\s*person",
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, name_lower) or re.search(pattern, title_lower):
            return True

    return False


def _check_excluded_company(company_lower: str, title_lower: str) -> tuple[bool, str]:
    """Check if company is a vendor/service provider that should be excluded."""
    vendor_title_keywords = ["developer", "designer", "consultant", "freelancer", "agency"]

    if any(kw in title_lower for kw in vendor_title_keywords):
        for pattern in EXCLUDED_COMPANY_PATTERNS:
            if re.search(pattern, company_lower):
                return True, f"vendor_company_with_{title_lower.split()[0]}"

    for pattern in EXCLUDED_COMPANY_PATTERNS:
        if re.search(pattern, company_lower):
            return True, f"excluded_company_pattern:{pattern.strip().replace('\\b', '')}"

    for vendor in VENDOR_INDICATORS:
        if vendor in company_lower:
            for kw in VENDOR_INDICATORS:
                if kw != vendor and kw in company_lower:
                    return True, f"vendor_company:{vendor}+{kw}"

    service_company_patterns = [
        r"(agency|consulting|solutions)\s+for\s",
        r"(marketing|creative|digital)\s+(agency|firm)",
        r"(software|tech|ai)\s+(company|startup|provider)",
        r"(restaurant|hotel|hospitality)\s+(tech|saas|software)",
    ]
    for pattern in service_company_patterns:
        if re.search(pattern, company_lower):
            return True, f"service_provider_company:{pattern}"

    return False, ""


def _check_vendor_title(title_lower: str) -> tuple[bool, str]:
    """Check if title indicates a service provider/vendor role."""
    for pattern in EXCLUDED_TITLE_PATTERNS:
        if re.search(pattern, title_lower):
            return True, pattern.strip().replace("\\b", "")

    vendor_title_keywords = [
        "consultant",
        "advisor",
        "freelancer",
        "agency",
        "designer",
        "developer",
        "writer",
        "coach",
        "trainer",
    ]
    for kw in vendor_title_keywords:
        if kw in title_lower:
            return True, kw

    return False, ""


def _score_buyer_fit(title_lower: str, company_lower: str) -> int:
    """Score how well the title represents a buyer persona."""
    score = 0

    if any(kw in title_lower for kw in BUYER_TITLE_KEYWORDS):
        score += 40
        if "founder" in title_lower or "owner" in title_lower:
            score += 10
        if "co-" in title_lower:
            score += 5

    if any(kw in title_lower for kw in OPERATIONS_TITLE_KEYWORDS):
        score += 25
        if "general manager" in title_lower:
            score += 10
        if "franchise" in title_lower:
            score += 15
        if "multi-unit" in title_lower or "multi location" in title_lower:
            score += 20

    if any(kw in title_lower for kw in LEADERSHIP_TITLE_KEYWORDS):
        score += 20
        if "ceo" in title_lower or "coo" in title_lower or "cfo" in title_lower:
            score += 10
        if "vp of" in title_lower or "director of" in title_lower:
            score += 5

    if any(kw in title_lower for kw in HOSPITALITY_KEYWORDS):
        if any(op in title_lower for op in OPERATIONS_TITLE_KEYWORDS):
            score += 25

    return score


def _score_company_quality(company_lower: str, title_lower: str) -> int:
    """Score company quality — prioritize operational businesses over solo operators."""
    score = 0

    for indicator in CHAIN_INDICATORS:
        if indicator in company_lower:
            score += 15

    multi_location_keywords = ["group", "holdings", "partners", "corp", "chain", "brands"]
    if any(kw in company_lower for kw in multi_location_keywords):
        score += 20

    if any(kw in company_lower for kw in HOSPITALITY_KEYWORDS):
        score += 15

    solo_indicators = ["freelance", "independent", "personal", " sole "]
    if any(ind in company_lower for ind in solo_indicators):
        score -= 25

    if any(kw in title_lower for kw in ["freelance", "independent", "sole"]):
        score -= 20

    if "consulting" in company_lower or "agency" in company_lower:
        score -= 30

    real_business_indicators = ["restaurant", "hotel", "resort", "clinic", "dental", "spa", "salon", "gym", "fitness"]
    if any(ind in company_lower for ind in real_business_indicators):
        score += 20

    return score


def _score_authority(title_lower: str) -> int:
    """Score decision-making authority."""
    score = 0

    if "owner" in title_lower or "founder" in title_lower or "co-founder" in title_lower:
        score += 30

    if "ceo" in title_lower or "president" in title_lower:
        score += 25

    if "coo" in title_lower or "cfo" in title_lower or "cto" in title_lower:
        score += 25

    if "vp" in title_lower or "vice president" in title_lower:
        score += 20

    if "director" in title_lower:
        score += 15

    if "head of" in title_lower:
        score += 15

    if "general manager" in title_lower or "gm " in title_lower:
        score += 20

    if "operations manager" in title_lower or "ops manager" in title_lower:
        score += 15

    if "franchise" in title_lower:
        score += 25

    if "regional" in title_lower or "district" in title_lower:
        score += 15

    return score


def _score_relevance(title_lower: str, company_lower: str, icp: dict) -> int:
    """Score relevance to ICP — buyer industries and roles."""
    score = 0

    buyer_roles = [r.lower() for r in (icp.get("buyer_roles") or [])]
    for role in buyer_roles:
        role_keywords = role.split()
        if any(kw in title_lower for kw in role_keywords if len(kw) > 2):
            score += 15
            break

    buyer_industries = [i.lower() for i in (icp.get("buyer_industries") or [])]
    for industry in buyer_industries:
        if industry in company_lower:
            score += 20
            break

    return score


def qualify_and_rank_leads(leads: list[dict], icp: dict) -> tuple[list[dict], dict]:
    """
    Apply commercial qualification to all leads and return ranked results.

    Returns (qualified_leads, qualification_stats)
    """
    qualified = []
    rejected = []
    stats = {
        "total": len(leads),
        "excluded_vendor": 0,
        "excluded_junk": 0,
        "qualified": 0,
        "avg_score": 0,
        "scores": [],
        "rejected_reasons": {},
        "drift_detected": 0,
    }

    for lead in leads:
        result = score_lead(lead, icp)

        if result["excluded"]:
            rejected.append({
                "lead": lead,
                "reason": result["excluded_reason"],
                "final_score": 0,
            })
            stats["rejected_reasons"][result["excluded_reason"]] = stats["rejected_reasons"].get(result["excluded_reason"], 0) + 1
            if "vendor" in result["excluded_reason"]:
                stats["excluded_vendor"] += 1
            elif "junk" in result["excluded_reason"]:
                stats["excluded_junk"] += 1
            continue

        if result["drift_flags"]:
            stats["drift_detected"] += 1

        qualified.append({
            "lead": lead,
            "score_breakdown": result,
            "final_score": result["final_score"],
        })
        stats["qualified"] += 1
        stats["scores"].append(result["final_score"])

    qualified.sort(key=lambda x: x["final_score"], reverse=True)

    if stats["scores"]:
        stats["avg_score"] = sum(stats["scores"]) / len(stats["scores"])

    final_leads = [item["lead"] for item in qualified]

    _log(f"[QUALIFICATION] total={stats['total']}, qualified={stats['qualified']}, excluded_vendor={stats['excluded_vendor']}, excluded_junk={stats['excluded_junk']}, drift={stats['drift_detected']}, avg_score={stats['avg_score']:.1f}")

    return final_leads, stats


def log_ranking_breakdown(lead: dict, score_breakdown: dict) -> None:
    """Log detailed ranking breakdown for debugging."""
    print(f"\n{'='*60}")
    print(f"[QUALIFICATION RANKING]")
    print(f"  Lead: {lead.get('name', 'N/A')} @ {lead.get('company', 'N/A')}")
    print(f"  Title: {lead.get('title', 'N/A')}")
    print(f"  Final Score: {score_breakdown.get('final_score', 0)}")
    print(f"  --- Score Breakdown ---")
    print(f"  buyer_score:      {score_breakdown.get('buyer_score', 0)}")
    print(f"  company_score:    {score_breakdown.get('company_score', 0)}")
    print(f"  authority_score:  {score_breakdown.get('authority_score', 0)}")
    print(f"  relevance_score:  {score_breakdown.get('relevance_score', 0)}")
    print(f"  drift_penalty:    {score_breakdown.get('drift_penalty', 0)}")
    print(f"  --- Highlights ---")
    for h in score_breakdown.get("highlights", []):
        print(f"    + {h}")
    print(f"  --- Penalties ---")
    for p in score_breakdown.get("penalties", []):
        print(f"    - {p}")
    print(f"  --- Drift Flags ---")
    for d in score_breakdown.get("drift_flags", []):
        print(f"    ! {d}")
    if score_breakdown.get("excluded"):
        print(f"  *** EXCLUDED: {score_breakdown.get('excluded_reason', 'unknown')} ***")
    print(f"{'='*60}\n")