import os
import json
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[icp_extractor] {message}")


def _normalize_string(value: str) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def _dedupe_and_cap(items: list, max_items: int = 8) -> list:
    if not items:
        return []
    seen = set()
    result = []
    for item in items:
        normalized = _normalize_string(item.lower())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(item.strip())
            if len(result) >= max_items:
                break
    return result


INDUSTRY_ROLES = {
    "restaurants": ["Restaurant Owner", "Operations Manager", "General Manager", "Franchise Owner", "Kitchen Manager", "Food & Beverage Director"],
    "restaurant": ["Restaurant Owner", "Operations Manager", "General Manager", "Franchise Owner", "Kitchen Manager", "Food & Beverage Director"],
    "hospitality": ["Hotel Manager", "Operations Director", "General Manager", "Revenue Manager", "VP Operations"],
    "healthcare": ["Practice Manager", "Clinic Director", "Operations Director", "Healthcare Administrator", "Medical Director"],
    "saas": ["RevOps", "VP Sales", "CRM Manager", "Sales Ops", "Head of Revenue"],
    "startups": ["Founder", "COO", "Head of Operations", "Co-Founder", "CEO"],
    "tech": ["CTO", "VP Engineering", "Product Manager", "Tech Lead", "Engineering Manager"],
    "technology": ["CTO", "VP Engineering", "Product Manager", "Tech Lead", "Engineering Manager"],
    "real estate": ["Broker Owner", "Operations Manager", "Real Estate Manager", "Brokerage Director"],
    "realestate": ["Broker Owner", "Operations Manager", "Real Estate Manager", "Brokerage Director"],
    "marketing": ["Marketing Director", "Growth Lead", "CMO", "Head of Marketing", "Demand Gen Manager"],
    "sales": ["VP Sales", "Sales Director", "Account Executive", "Sales Manager", "Head of Revenue"],
    "finance": ["CFO", "Finance Director", "Controller", "VP Finance", "Financial Controller"],
    "accounting": ["CFO", "Controller", "Finance Manager", "Accounting Manager", "Bookkeeping Director"],
    "hr": ["HR Director", "People Ops", "CHRO", "HR Manager", "Talent Lead"],
    "legal": ["Practice Manager", "Operations Director", "Firm Administrator", "Managing Partner"],
    "education": ["School Director", "Operations Manager", "Education Administrator", "Principal"],
    "retail": ["Store Manager", "Operations Manager", "Retail Director", "Store Owner", "District Manager"],
    "manufacturing": ["Operations Manager", "Production Manager", "Plant Manager", "Manufacturing Director", "COO"],
    "construction": ["Project Manager", "Operations Manager", "Construction Manager", "Owner", "General Contractor"],
    "logistics": ["Operations Manager", "Logistics Manager", "Supply Chain Manager", "Fleet Manager", "Warehouse Manager"],
    "food": ["Operations Manager", "Food Safety Manager", "Production Manager", "Kitchen Manager", "Owner"],
    "agencies": ["Agency Owner", "Account Director", "Operations Manager", "Managing Director", "Client Services Director"],
    "agency": ["Agency Owner", "Account Director", "Operations Manager", "Managing Director", "Client Services Director"],
}

OFFER_SEPARATORS = [" for ", " to ", " targeting ", " helping ", " for ", " serving ", " for businesses in "]

INDUSTRY_NORMALIZATION = {
    "restaurant": "restaurants",
    "startup": "startups",
    "realestate": "real estate",
    "hospitality": "restaurants",
    "food": "restaurants",
    "agency": "agencies",
}


def _extract_offer(user_input: str) -> str:
    """Extract just the product/service from user input"""
    user_input_lower = user_input.lower()

    for sep in OFFER_SEPARATORS:
        if sep in user_input_lower:
            parts = user_input.split(sep, 1)
            offer = parts[0].strip()
            if len(offer) > 2:
                return _normalize_string(offer)

    words = user_input.replace(",", " ").replace("-", " ").split()
    if len(words) >= 2:
        offer = " ".join(words[:-1])
        if len(offer) > 2:
            return _normalize_string(offer)

    return _normalize_string(user_input)


EXCLUDE_PLURALIZATION = {"healthcare", "saas", "real estate", "marketing", "accounting", "logistics", "hr"}


def _normalize_industries(industries: list) -> list:
    """Normalize industry names to consistent plurals"""
    normalized = []
    for ind in industries:
        ind_lower = ind.lower().strip()
        if ind_lower in INDUSTRY_NORMALIZATION:
            normalized.append(INDUSTRY_NORMALIZATION[ind_lower])
        else:
            if not ind_lower.endswith("s") and ind_lower not in EXCLUDE_PLURALIZATION:
                normalized.append(ind_lower + "s")
            else:
                normalized.append(ind_lower)
    return normalized


def _get_industry_roles(industries: list) -> list:
    """Get target roles based on detected industries"""
    roles = []
    for ind in industries:
        if ind in INDUSTRY_ROLES:
            roles.extend(INDUSTRY_ROLES[ind])
        elif ind.rstrip("s") in INDUSTRY_ROLES:
            roles.extend(INDUSTRY_ROLES[ind.rstrip("s")])
    return roles


def _find_industries_in_input(user_input: str) -> list:
    """Find industries in user input by looking for industry keywords"""
    user_lower = user_input.lower()
    found = []

    industry_keywords = {
        "restaurants": ["restaurant", "restaurants", "dining", "food service", "cafe", "bistro", "eatery"],
        "hospitality": ["hotel", "hospitality", "resort", "inn", "motel", "lodge"],
        "healthcare": ["healthcare", "medical", "clinic", "hospital", "doctor", "practice", "health"],
        "saas": ["saas"],
        "startups": ["startup", "startups", "early stage", "founder"],
        "tech": ["tech", "technology", "tech company"],
        "technology": ["tech", "technology", "tech company"],
        "real estate": ["real estate", "realestate", "property", "brokerage"],
        "marketing": ["marketing agency", "marketing firm", "advertising agency", "digital agency"],
        "sales": ["sales", "sales team"],
        "finance": ["finance", "financial", "banking"],
        "accounting": ["accounting", "accountant", "bookkeeping"],
        "hr": ["hr", "human resources", "people ops", "talent"],
        "legal": ["legal", "law firm", "lawyer", "attorney"],
        "education": ["education", "school", "university", "training"],
        "retail": ["retail", "retailer", "store", "shop"],
        "manufacturing": ["manufacturing", "manufacture", "factory", "production"],
        "construction": ["construction", "contractor", "builder"],
        "logistics": ["logistics", "shipping", "freight", "supply chain"],
        "food": ["food", "catering", "food service"],
        "agencies": ["agency", "agencies"],
    }

    for ind, keywords in industry_keywords.items():
        for kw in keywords:
            if kw in user_lower:
                if ind not in found:
                    found.append(ind)
                break

    return found


def _generate_industry_keywords(offer: str, industries: list) -> list:
    """Generate industry-aware keywords"""
    keywords = []

    offer_words = offer.lower().split()

    for ind in industries:
        keywords.append(f"{offer} {ind}")
        keywords.append(f"{offer} for {ind}")

        if "restaurant" in ind:
            keywords.extend([
                f"{offer} restaurant operations",
                f"{offer} restaurant management",
                f"{offer} hospitality industry",
            ])
        elif "healthcare" in ind:
            keywords.extend([
                f"{offer} healthcare operations",
                f"{offer} medical practice",
                f"{offer} clinic management",
            ])
        elif "startup" in ind:
            keywords.extend([
                f"{offer} startup operations",
                f"{offer} early stage company",
            ])
        elif "saas" in ind:
            keywords.extend([
                f"{offer} SaaS operations",
                f"{offer} software company",
            ])
        elif "real estate" in ind:
            keywords.extend([
                f"{offer} real estate operations",
                f"{offer} property management",
            ])
        elif "marketing" in ind:
            keywords.extend([
                f"{offer} marketing operations",
                f"{offer} growth team",
            ])

    return keywords[:8]


def _get_deterministic_icp(user_input: str, existing_context: Optional[dict] = None) -> dict:
    """Generate deterministic ICP extraction when AI is unavailable"""
    _log("Using deterministic fallback extraction")

    user_input = (user_input or "").strip()
    if not user_input:
        return _empty_icp("fallback")

    _log(f"raw_input='{user_input}'")

    offer = _extract_offer(user_input)
    _log(f"extracted_offer='{offer}'")

    detected_industries = _find_industries_in_input(user_input)
    normalized_industries = _dedupe_and_cap(_normalize_industries(detected_industries), 6)
    _log(f"normalized_industries={normalized_industries}")

    industry_roles = _get_industry_roles(normalized_industries)
    _log(f"inferred_roles={industry_roles}")

    keywords = _generate_industry_keywords(offer, normalized_industries)

    search_hints = []
    for role in industry_roles[:3]:
        if normalized_industries:
            primary_ind = normalized_industries[0]
            search_hints.append(f"{role} {primary_ind}")
        else:
            search_hints.append(role)

    return {
        "offer": offer,
        "industries": normalized_industries,
        "target_roles": _dedupe_and_cap(industry_roles, 8),
        "company_types": [],
        "pain_points": [],
        "keywords": _dedupe_and_cap(keywords, 8),
        "search_hints": _dedupe_and_cap(search_hints, 4),
        "mode": "fallback"
    }


def _empty_icp(mode: str = "fallback") -> dict:
    return {
        "offer": "",
        "industries": [],
        "target_roles": [],
        "company_types": [],
        "pain_points": [],
        "keywords": [],
        "search_hints": [],
        "mode": mode
    }


def extract_structured_icp(
    user_input: str,
    existing_context: Optional[dict] = None
) -> dict:
    """
    Extract structured ICP from user input using AI or fallback.

    Args:
        user_input: Raw user input describing what they sell/target
        existing_context: Optional existing context from conversation

    Returns:
        dict with offer, industries, target_roles, company_types, pain_points,
        keywords, search_hints, and mode (ai/fallback)
    """
    user_input = (user_input or "").strip()
    if not user_input:
        _log("No input provided, returning empty ICP")
        return _empty_icp("fallback")

    _log(f"Extracting ICP from: '{user_input}'")

    if not OPENAI_API_KEY:
        _log("OPENAI_API_KEY not configured, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)

    system_text = """You are an ICP (Ideal Customer Profile) extraction engine for B2B sales.

Given user input about what they sell and who they target, extract a structured ICP.

Return ONLY valid JSON with this structure:
{
  "offer": "what they sell (product/service name)",
  "industries": ["industry1", "industry2", ...],
  "target_roles": ["role1", "role2", ...],
  "company_types": ["type1", "type2", ...],
  "pain_points": ["pain1", "pain2", ...],
  "keywords": ["keyword1", "keyword2", ...],
  "search_hints": ["hint1", "hint2", ...]
}

Rules:
- offer: concise product/service name (e.g., "CRM software", "AI automations")
- industries: 2-6 relevant industries (e.g., ["SaaS", "startups", "healthcare"])
- target_roles: 3-8 job titles that would be buyers (e.g., ["CRM Manager", "VP Sales"])
- company_types: company descriptors (e.g., ["startups", "enterprise", "multi-location"])
- pain_points: common problems this product solves (e.g., ["manual workflows", "pipeline management"])
- keywords: search-friendly terms combining product + industry/role
- search_hints: hints for lead search (e.g., ["operations teams", "sales leadership"])
- Be specific but not fabricate data
- Maximum 8 items per list"""

    context_info = ""
    if existing_context:
        if existing_context.get("service"):
            context_info += f"Previous service: {existing_context['service']}\n"
        if existing_context.get("target"):
            context_info += f"Previous target: {existing_context['target']}\n"

    user_text = f"""User input: {user_input}
{context_info}

Extract the structured ICP."""

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_text}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        _log("Sending request to OpenAI for ICP extraction")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )

        if response.status_code == 401:
            _log("OpenAI API key is invalid")
            return _get_deterministic_icp(user_input, existing_context)

        if response.status_code == 429:
            _log("OpenAI API quota exceeded")
            return _get_deterministic_icp(user_input, existing_context)

        if response.status_code >= 500:
            _log(f"OpenAI API server error: {response.status_code}")
            return _get_deterministic_icp(user_input, existing_context)

        response.raise_for_status()

        data = response.json()

        try:
            output_text = data["output"][0]["content"][0]["text"].strip()
        except (KeyError, IndexError):
            output_text = data.get("output_text", "").strip()

        if not output_text:
            _log("Empty response from OpenAI")
            return _get_deterministic_icp(user_input, existing_context)

        result = json.loads(output_text)

        icp = {
            "offer": _normalize_string(result.get("offer", user_input)),
            "industries": _dedupe_and_cap(result.get("industries", []), 6),
            "target_roles": _dedupe_and_cap(result.get("target_roles", []), 8),
            "company_types": _dedupe_and_cap(result.get("company_types", []), 4),
            "pain_points": _dedupe_and_cap(result.get("pain_points", []), 6),
            "keywords": _dedupe_and_cap(result.get("keywords", []), 8),
            "search_hints": _dedupe_and_cap(result.get("search_hints", []), 4),
            "mode": "ai"
        }

        _log(f"mode=ai")
        _log(f"industries={icp['industries']}")
        _log(f"target_roles={icp['target_roles']}")
        _log(f"keywords={icp['keywords']}")
        _log(f"search_hints={icp['search_hints']}")

        return icp

    except requests.Timeout:
        _log("OpenAI request timed out, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)
    except requests.ConnectionError as e:
        _log(f"OpenAI connection error: {e}, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)
    except json.JSONDecodeError as e:
        _log(f"Failed to parse AI response as JSON: {e}")
        return _get_deterministic_icp(user_input, existing_context)
    except Exception as e:
        _log(f"Unexpected error during ICP extraction: {e}")
        return _get_deterministic_icp(user_input, existing_context)