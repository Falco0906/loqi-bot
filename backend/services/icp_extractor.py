import os
import json
import re
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


BUYER_INDUSTRY_KEYWORDS = {
    "restaurants": ["restaurant", "restaurants", "dining", "food service", "cafe", "bistro", "eatery", "pizza", "burger", "coffee shop", "bar", "grill", "kitchen"],
    "hospitality": ["hotel", "hotels", "hospitality", "resort", "resorts", "inn", "motel", "lodge", "bed and breakfast", "airbnb", "vacation rental"],
    "healthcare": ["healthcare", "medical", "clinic", "clinics", "hospital", "hospitals", "doctor", "doctors", "practice", "practices", "health", "medical practice"],
    "dental": ["dentist", "dental", "dentists", "dental practice", "dental clinic", "dentistry"],
    "wellness": ["spa", "salon", "beauty", "wellness", "massage", "chiropractor", "yoga"],
    "saas": ["saas", "software", "tech company", "startup", "startups", "early stage"],
    "startups": ["startup", "startups", "early stage", "founder", "founding"],
    "tech": ["tech", "technology", "tech company", "software company"],
    "real estate": ["real estate", "realestate", "property", "brokerage", "real estate broker", "property management"],
    "finance": ["finance", "financial", "banking", "accounting", "accountant"],
    "legal": ["legal", "law firm", "lawyer", "lawyers", "attorney", "attorneys", "law practice"],
    "education": ["education", "school", "schools", "university", "universities", "training", "college"],
    "retail": ["retail", "retailer", "store", "stores", "shop", "shops", "ecommerce"],
    "gym": ["gym", "gyms", "fitness", "fitness center", "health club", "athletic"],
    "manufacturing": ["manufacturing", "manufacture", "factory", "factories", "production"],
    "construction": ["construction", "contractor", "contractors", "builder", "builders"],
    "logistics": ["logistics", "shipping", "freight", "supply chain", "trucking"],
    "agencies": ["agency", "agencies", "marketing agency", "advertising agency", "digital agency"],
    "consulting": ["consulting", "consultant", "consultants", "advisory"],
}

BUYER_INDUSTRY_NORMALIZATION = {
    "restaurant": "restaurants",
    "restaurant owner": "restaurants",
    "startup": "startups",
    "dental practice": "dental",
    "dentist": "dental",
    "law firm": "legal",
    "realestate": "real estate",
    "gym owner": "gym",
    "fitness center": "gym",
    "salon": "wellness",
    "spa": "wellness",
}

BUYER_ROLE_MAPPINGS = {
    "restaurants": [
        "Restaurant Owner",
        "General Manager",
        "Operations Manager",
        "Franchise Owner",
        "Kitchen Manager",
        "Food & Beverage Director",
        "Hospitality Director",
        "Multi-Unit Operator",
    ],
    "hospitality": [
        "Hotel Manager",
        "General Manager",
        "Operations Director",
        "Revenue Manager",
        "VP Operations",
        "Hospitality Director",
        "Property Manager",
    ],
    "healthcare": [
        "Practice Manager",
        "Clinic Director",
        "Operations Director",
        "Healthcare Administrator",
        "Medical Director",
        "Physician Owner",
        "Practice Owner",
    ],
    "dental": [
        "Dental Practice Owner",
        "Practice Manager",
        "Dental Director",
        "Dentist Owner",
        "Office Manager",
    ],
    "wellness": [
        "Spa Owner",
        "Salon Owner",
        "Wellness Center Owner",
        "General Manager",
        "Operations Manager",
    ],
    "saas": [
        "RevOps",
        "VP Sales",
        "CRM Manager",
        "Sales Ops",
        "Head of Revenue",
        "COO",
    ],
    "startups": [
        "Founder",
        "Co-Founder",
        "COO",
        "Head of Operations",
        "CEO",
        "Managing Partner",
    ],
    "tech": [
        "CTO",
        "VP Engineering",
        "Product Manager",
        "Tech Lead",
        "Engineering Manager",
        "CEO",
    ],
    "real estate": [
        "Broker Owner",
        "Operations Manager",
        "Real Estate Manager",
        "Brokerage Director",
        "Managing Broker",
    ],
    "finance": [
        "CFO",
        "Finance Director",
        "Controller",
        "VP Finance",
        "Financial Controller",
        "Managing Partner",
    ],
    "legal": [
        "Managing Partner",
        "Office Manager",
        "Firm Administrator",
        "Practice Manager",
        "Operations Director",
    ],
    "education": [
        "School Director",
        "Operations Manager",
        "Education Administrator",
        "Principal",
        "Executive Director",
    ],
    "retail": [
        "Store Manager",
        "Operations Manager",
        "Retail Director",
        "Store Owner",
        "District Manager",
    ],
    "gym": [
        "Gym Owner",
        "General Manager",
        "Fitness Center Owner",
        "Operations Manager",
        "Head Coach",
    ],
    "manufacturing": [
        "Operations Manager",
        "Production Manager",
        "Plant Manager",
        "Manufacturing Director",
        "COO",
    ],
    "construction": [
        "Project Manager",
        "Operations Manager",
        "Construction Manager",
        "Owner",
        "General Contractor",
    ],
    "logistics": [
        "Operations Manager",
        "Logistics Manager",
        "Supply Chain Manager",
        "Fleet Manager",
        "Warehouse Manager",
    ],
    "agencies": [
        "Agency Owner",
        "Account Director",
        "Operations Manager",
        "Managing Director",
        "Client Services Director",
    ],
    "consulting": [
        "Managing Partner",
        "Principal",
        "Operations Director",
        "Practice Leader",
    ],
}

EXCLUDED_ROLES = [
    "developer",
    "developer",
    "designer",
    "web designer",
    "ui designer",
    "ux designer",
    "freelancer",
    "independent",
    "consultant",
    "advisor",
    "agency owner",
    "agency director",
    "contractor",
    "contractor",
    "specialist",
    "marketer",
    "marketing specialist",
    "seo specialist",
    "content writer",
    "copywriter",
    "blogger",
    "influencer",
    "coach",
    "trainer",
    "mentor",
    "virtual assistant",
    "va",
    "account manager",
    "sales rep",
    "recruiter",
    "recruiting",
    "staffing",
]

EXCLUDED_ROLE_PATTERNS = [
    r"\bdev(eloper)?\b",
    r"\bdesign(er)?\b",
    r"\bfreelance\b",
    r"\bfreelancer\b",
    r"\bcontract(or|or)?\b",
    r"\bconsult(ant|ing)?\b",
    r"\badvisor\b",
    r"\bagency\b",
    r"\bseo\b",
    r"\bmarketing\b.*specialist",
    r"\bspecialist\b.*market",
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
]

OFFER_SEPARATORS = [
    " for ",
    " to ",
    " targeting ",
    " helping ",
    " serving ",
    " for businesses in ",
    " for ",
    " to ",
]


def _extract_offer(user_input: str) -> str:
    """Extract just the product/service from user input (before the 'for/to' separator)"""
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


def _extract_buyer_industry(user_input: str) -> list:
    """Extract the buyer industry from 'X for Y' pattern - the BUYER not the service"""
    user_lower = user_input.lower()
    found = []

    for ind, keywords in BUYER_INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in user_lower:
                normalized = BUYER_INDUSTRY_NORMALIZATION.get(ind, ind)
                if normalized not in found:
                    found.append(normalized)
                break

    return _dedupe_and_cap(found, 4)


def _extract_service_category(user_input: str) -> str:
    """Extract the service category being sold"""
    offer = _extract_offer(user_input)
    offer_lower = offer.lower()

    service_categories = {
        "website": ["website", "web design", "web development", "landing page", "web site"],
        "crm": ["crm", "crm software", "customer relationship"],
        "marketing": ["marketing", "digital marketing", "seo", "sem", "ppc", "advertising"],
        "automation": ["automation", "automate", "automated", "workflow"],
        "ai": ["ai", "artificial intelligence", "machine learning", "ml"],
        "calling": ["calling", "phone", "telephone", "voip", "calling software"],
        "catering": ["catering", "food service", "catering service"],
        "accounting": ["accounting", "bookkeeping", "accountant", "financial software"],
        "scheduling": ["scheduling", "booking", "appointment", "calendar"],
        "pos": ["pos", "point of sale", "payment"],
        "video": ["video", "videography", "production"],
        "photo": ["photography", "photo", "photoshoot"],
        "security": ["security", "cybersecurity", "alarm"],
        "cleaning": ["cleaning", "janitorial", "clean"],
        "security": ["security", "guard", "protection"],
    }

    for cat, keywords in service_categories.items():
        for kw in keywords:
            if kw in offer_lower:
                return cat

    return offer


def _get_buyer_roles(industries: list) -> list:
    """Get BUYER roles based on detected industries - the people who BUY, not provide"""
    roles = []
    for ind in industries:
        if ind in BUYER_ROLE_MAPPINGS:
            roles.extend(BUYER_ROLE_MAPPINGS[ind])
        elif ind.rstrip("s") in BUYER_ROLE_MAPPINGS:
            roles.extend(BUYER_ROLE_MAPPINGS[ind.rstrip("s")])
    return _dedupe_and_cap(roles, 10)


def _get_excluded_roles(service_category: str) -> list:
    """Get roles to exclude based on service category"""
    return EXCLUDED_ROLES


def _is_excluded_role(title: str) -> bool:
    """Check if a lead title matches excluded roles"""
    title_lower = (title or "").lower()

    for pattern in EXCLUDED_ROLE_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return True

    for excluded in EXCLUDED_ROLES:
        if excluded in title_lower:
            return True

    return False


def _generate_buyer_keywords(offer: str, buyer_industries: list, buyer_roles: list) -> list:
    """Generate buyer-focused keywords - NOT service provider keywords"""
    keywords = []

    for ind in buyer_industries:
        for role in buyer_roles[:3]:
            keywords.append(f"{role} {ind}")
            keywords.append(f"{role} at {ind}")

    return _dedupe_and_cap(keywords, 10)


def _generate_search_hints(offer: str, buyer_industries: list, buyer_roles: list) -> list:
    """Generate search hints for finding buyers"""
    hints = []

    for ind in buyer_industries[:2]:
        for role in buyer_roles[:3]:
            hints.append(f"{role} {ind}")

    return _dedupe_and_cap(hints, 6)


def _get_deterministic_icp(user_input: str, existing_context: Optional[dict] = None) -> dict:
    """Generate deterministic ICP extraction when AI is unavailable - BUYER-FOCUSED"""
    _log("Using deterministic fallback extraction (buyer-intent mode)")

    user_input = (user_input or "").strip()
    if not user_input:
        return _empty_icp("fallback")

    _log(f"raw_input='{user_input}'")

    offer = _extract_offer(user_input)
    _log(f"extracted_offer='{offer}'")

    service_category = _extract_service_category(user_input)
    _log(f"service_category='{service_category}'")

    buyer_industries = _extract_buyer_industry(user_input)
    _log(f"buyer_industries={buyer_industries}")

    buyer_roles = _get_buyer_roles(buyer_industries)
    _log(f"buyer_roles={buyer_roles}")

    excluded_roles = _get_excluded_roles(service_category)
    _log(f"excluded_roles={excluded_roles}")

    keywords = _generate_buyer_keywords(offer, buyer_industries, buyer_roles)
    _log(f"keywords={keywords}")

    search_hints = _generate_search_hints(offer, buyer_industries, buyer_roles)
    _log(f"search_hints={search_hints}")

    return {
        "offer": offer,
        "service_category": service_category,
        "buyer_industries": buyer_industries,
        "buyer_roles": _dedupe_and_cap(buyer_roles, 10),
        "excluded_roles": excluded_roles,
        "company_types": [],
        "pain_points": [],
        "keywords": keywords,
        "search_hints": search_hints,
        "mode": "fallback"
    }


def _empty_icp(mode: str = "fallback") -> dict:
    return {
        "offer": "",
        "service_category": "",
        "buyer_industries": [],
        "buyer_roles": [],
        "excluded_roles": [],
        "company_types": [],
        "pain_points": [],
        "keywords": [],
        "search_hints": [],
        "mode": mode
    }


def _transform_ai_response_to_buyer_schema(result: dict) -> dict:
    """Transform AI response to new buyer-intent schema"""
    buyer_industries = _dedupe_and_cap(result.get("buyer_industries", result.get("industries", [])), 4)
    buyer_roles = _dedupe_and_cap(result.get("buyer_roles", result.get("target_roles", [])), 10)
    excluded_roles = result.get("excluded_roles", [])

    if not excluded_roles:
        excluded_roles = _get_excluded_roles(result.get("service_category", ""))

    return {
        "offer": result.get("offer", ""),
        "service_category": result.get("service_category", ""),
        "buyer_industries": buyer_industries,
        "buyer_roles": buyer_roles,
        "excluded_roles": excluded_roles,
        "company_types": _dedupe_and_cap(result.get("company_types", []), 4),
        "pain_points": _dedupe_and_cap(result.get("pain_points", []), 6),
        "keywords": _dedupe_and_cap(result.get("keywords", []), 10),
        "search_hints": _dedupe_and_cap(result.get("search_hints", []), 6),
        "mode": "ai"
    }


def extract_structured_icp(
    user_input: str,
    existing_context: Optional[dict] = None
) -> dict:
    """
    Extract structured BUYER-INTENT ICP from user input using AI or fallback.

    CRITICAL: This extracts WHO BUYS, not what is sold.
    Input: "websites for restaurants"
    Output: buyer_roles = [Restaurant Owner, General Manager, ...]
    NOT: [Web Developer, Designer, ...]

    Args:
        user_input: Raw user input describing what they sell/target
        existing_context: Optional existing context from conversation

    Returns:
        dict with buyer-focused fields:
        - offer: what they sell
        - service_category: category of service
        - buyer_industries: industries that are buyers (not service industries)
        - buyer_roles: job titles of buyers (not service providers)
        - excluded_roles: roles to exclude from results
        - keywords: buyer-focused search keywords
        - search_hints: search hints for finding buyers
        - mode: "ai" or "fallback"
    """
    user_input = (user_input or "").strip()
    if not user_input:
        _log("No input provided, returning empty ICP")
        return _empty_icp("fallback")

    _log(f"Extracting BUYER-INTENT ICP from: '{user_input}'")

    if not OPENAI_API_KEY:
        _log("OPENAI_API_KEY not configured, using deterministic fallback (buyer-intent)")
        return _get_deterministic_icp(user_input, existing_context)

    system_text = """You are a BUYER-INTENT ICP extraction engine for B2B sales.

CRITICAL: Your job is to identify WHO BUYS the product, not what they sell.

Input examples:
- "websites for restaurants" → buyer_roles = Restaurant Owner, General Manager
- "crm for startups" → buyer_roles = Founder, COO, Head of Operations
- "automation for dentists" → buyer_roles = Dental Practice Owner, Practice Manager

WRONG:
- "websites for restaurants" → Web Developer, Designer (NOT BUYERS)
- "crm for startups" → CRM Consultant (NOT BUYERS)
- "marketing for gyms" → Marketing Specialist (NOT BUYERS)

Return ONLY valid JSON with this structure:
{
  "offer": "what they sell (product/service name)",
  "service_category": "category (website, crm, marketing, automation, etc)",
  "buyer_industries": ["industry1", "industry2", ...],
  "buyer_roles": ["role1", "role2", ...],
  "excluded_roles": ["developer", "designer", "consultant", "freelancer", "agency owner"],
  "company_types": ["type1", "type2", ...],
  "pain_points": ["pain1", "pain2", ...],
  "keywords": ["buyer keyword1", "buyer keyword2", ...],
  "search_hints": ["search hint1", "search hint2", ...]
}

Rules:
- offer: concise product/service name (e.g., "CRM software", "Website design")
- service_category: category of service being sold
- buyer_industries: 2-4 industries where buyers work (e.g., ["restaurants", "healthcare"])
- buyer_roles: 4-10 job titles of DECISION MAKERS/BUYERS (NOT service providers)
- excluded_roles: roles to exclude (developers, designers, freelancers, consultants, agencies)
- keywords: search-friendly terms for finding buyers (NOT service providers)
- search_hints: LinkedIn search-style hints for buyer discovery
- Be specific but NOT fabricate data
- Maximum 10 items per list"""

    context_info = ""
    if existing_context:
        if existing_context.get("service"):
            context_info += f"Previous service: {existing_context['service']}\n"
        if existing_context.get("target"):
            context_info += f"Previous target: {existing_context['target']}\n"

    user_text = f"""User input: {user_input}
{context_info}

Extract the BUYER-INTENT ICP. Remember: identify WHO BUYS, not what is sold."""

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
        _log("Sending request to OpenAI for buyer-intent ICP extraction")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )

        if response.status_code == 401:
            _log("OpenAI API key is invalid, using deterministic fallback")
            return _get_deterministic_icp(user_input, existing_context)

        if response.status_code == 429:
            _log("OpenAI API quota exceeded, using deterministic fallback")
            return _get_deterministic_icp(user_input, existing_context)

        if response.status_code >= 500:
            _log(f"OpenAI API server error: {response.status_code}, using deterministic fallback")
            return _get_deterministic_icp(user_input, existing_context)

        response.raise_for_status()

        data = response.json()

        try:
            output_text = data["output"][0]["content"][0]["text"].strip()
        except (KeyError, IndexError):
            output_text = data.get("output_text", "").strip()

        if not output_text:
            _log("Empty response from OpenAI, using deterministic fallback")
            return _get_deterministic_icp(user_input, existing_context)

        result = json.loads(output_text)

        icp = _transform_ai_response_to_buyer_schema(result)

        _log(f"mode=ai")
        _log(f"buyer_industries={icp['buyer_industries']}")
        _log(f"buyer_roles={icp['buyer_roles']}")
        _log(f"excluded_roles={icp['excluded_roles']}")
        _log(f"keywords={icp['keywords']}")

        return icp

    except requests.Timeout:
        _log("OpenAI request timed out, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)
    except requests.ConnectionError as e:
        _log(f"OpenAI connection error: {e}, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)
    except json.JSONDecodeError as e:
        _log(f"Failed to parse AI response as JSON: {e}, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)
    except Exception as e:
        _log(f"Unexpected error during ICP extraction: {e}, using deterministic fallback")
        return _get_deterministic_icp(user_input, existing_context)


def is_lead_excluded(lead: dict, icp: dict) -> tuple[bool, str]:
    """
    Check if a lead should be excluded based on ICP criteria.
    Returns (is_excluded, reason)
    """
    title = (lead.get("title") or "").lower()
    name = (lead.get("name") or "").lower()
    company = (lead.get("company") or "").lower()

    excluded_roles = icp.get("excluded_roles", [])

    for excluded in excluded_roles:
        if excluded.lower() in title:
            return True, f"excluded_role:{excluded}"

    if _is_excluded_role(title):
        return True, "excluded_pattern_match"

    excluded_company_keywords = ["agency", "consulting", "solutions", "services", "digital"]
    for keyword in excluded_company_keywords:
        if keyword in company and any(r in title for r in ["developer", "designer", "consultant"]):
            return True, f"excluded_company_type"

    return False, ""