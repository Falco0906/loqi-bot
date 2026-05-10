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


def _get_deterministic_icp(user_input: str, existing_context: Optional[dict] = None) -> dict:
    """Generate deterministic ICP extraction when AI is unavailable"""
    _log("AI unavailable, using deterministic extraction")

    user_input = (user_input or "").strip()
    if not user_input:
        return _empty_icp("fallback")

    words = user_input.replace(",", " ").replace("/", " ").split()

    offer = _normalize_string(user_input)

    industries = []
    target_roles = []
    keywords = []
    search_hints = []

    common_industries = {
        "restaurant", "restaurants", "hospitality", "healthcare", "finance",
        "saas", "startup", "startups", "tech", "technology", "retail",
        "manufacturing", "construction", "real estate", "legal", "education",
        "marketing", "sales", "accounting", "logistics", "food"
    }

    common_roles = {
        "crm": ["CRM Manager", "RevOps", "Sales Ops"],
        "ai": ["CTO", "VP Engineering", "Product Manager", "Founder"],
        "automation": ["Operations Manager", "VP Operations", "Founder"],
        "marketing": ["CMO", "Marketing Director", "Growth Lead"],
        "sales": ["VP Sales", "Sales Director", "Account Executive"],
        "hr": ["HR Director", "People Ops", "CHRO"],
        "accounting": ["CFO", "Controller", "Finance Manager"],
    }

    for word in words:
        word_lower = word.lower()
        if word_lower in common_industries:
            industries.append(word_lower)
        if word_lower in common_roles:
            target_roles.extend(common_roles[word_lower])

    if not industries and len(words) >= 2:
        industries.append(words[-1])

    if industries:
        keywords.append(f"{offer} {industries[0]}")
    else:
        keywords.append(offer)

    search_hints = [f"{r} {industries[0]}" if industries else r for r in target_roles[:2]]

    return {
        "offer": offer,
        "industries": _dedupe_and_cap(industries, 6),
        "target_roles": _dedupe_and_cap(target_roles, 8),
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