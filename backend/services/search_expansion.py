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
    print(f"[search_expansion] {message}")


def _dedupe_and_cap(items: list, max_items: int = 8) -> list:
    if not items:
        return []
    seen = set()
    result = []
    for item in items:
        normalized = item.lower().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(item.strip())
            if len(result) >= max_items:
                break
    return result


def _get_deterministic_expansion(service: str, target: Optional[str], icp: Optional[dict] = None) -> dict:
    """Generate deterministic expansion when AI is unavailable - BUYER-FOCUSED"""
    _log("Using deterministic fallback expansion (buyer-intent mode)")
    
    service_clean = service.strip() if service else ""
    target_clean = target.strip() if target else ""
    
    roles = []
    industries = []
    keywords = []
    excluded_roles = []
    
    buyer_roles = icp.get("buyer_roles", []) if icp else []
    buyer_industries = icp.get("buyer_industries", []) if icp else []
    excluded_roles = icp.get("excluded_roles", []) if icp else []
    keywords_from_icp = icp.get("keywords", []) if icp else []
    
    if buyer_roles:
        roles = buyer_roles[:6]
        _log(f"Using buyer_roles from ICP: {roles[:3]}...")
    else:
        roles = [service_clean] if service_clean else []
    
    if buyer_industries:
        industries = buyer_industries[:4]
        _log(f"Using buyer_industries from ICP: {industries}")
    else:
        industries = [target_clean] if target_clean else []
    
    if keywords_from_icp:
        keywords = keywords_from_icp[:8]
        _log(f"Using buyer-focused keywords from ICP: {keywords[:3]}...")
    else:
        if buyer_roles and buyer_industries:
            for role in buyer_roles[:3]:
                for ind in buyer_industries[:2]:
                    keywords.append(f"{role} {ind}")
        elif service_clean and target_clean:
            keywords.append(f"{service_clean} {target_clean}")
            keywords.append(f"{service_clean} for {target_clean}")
        elif service_clean:
            keywords.append(service_clean)
    
    search_queries = []
    for kw in keywords[:8]:
        clean_kw = kw.replace('"', '').strip()
        search_queries.append(f'site:linkedin.com/in "{clean_kw}"')
    
    _log(f"Generated {len(search_queries)} buyer-focused search queries")
    
    return {
        "roles": _dedupe_and_cap(roles, 8),
        "industries": _dedupe_and_cap(industries, 4),
        "keywords": _dedupe_and_cap(keywords, 8),
        "search_queries": search_queries,
        "excluded_roles": excluded_roles,
    }


def expand_search_intent(
    service: str,
    target: Optional[str] = None,
    icp: Optional[dict] = None
) -> dict:
    """
    Expand search intent using AI semantic understanding - BUYER-FOCUSED.
    
    Args:
        service: What the user sells (e.g., "CRM", "AI automation")
        target: Optional target audience (e.g., "startups", "law firms")
        icp: Optional structured ICP from extract_structured_icp() - NEW: uses buyer_roles, buyer_industries
    
    Returns:
        dict with buyer-focused roles, industries, keywords, and search_queries
    """
    if not service:
        _log("No service provided, using empty expansion")
        return _get_deterministic_expansion("", None, icp)
    
    if not OPENAI_API_KEY:
        _log("OPENAI_API_KEY not configured, using deterministic fallback (buyer-intent)")
        return _get_deterministic_expansion(service, target, icp)
    
    _log(f"Expanding BUYER-INTENT: service='{service}', target='{target}'")
    
    has_icp = icp and icp.get("mode") == "ai"
    use_new_schema = icp and "buyer_roles" in icp
    
    if has_icp:
        if use_new_schema:
            _log(f"Using NEW buyer-intent ICP: offer='{icp.get('offer')}', buyer_industries={icp.get('buyer_industries')}, buyer_roles={icp.get('buyer_roles')[:3]}...")
            _log(f"excluded_roles={icp.get('excluded_roles', [])}")
        else:
            _log(f"Using OLD schema ICP (will transform): offer='{icp.get('offer')}', industries={icp.get('industries')}, roles={icp.get('target_roles')}")
    
    system_text = """You are a BUYER-INTENT lead search strategist. Your job is to generate search queries that find DECISION MAKERS/BUYERS, not service providers.

CRITICAL EXAMPLES:
- "websites for restaurants" → search: "restaurant owner linkedin", "general manager restaurant linkedin"
  WRONG: "web developer restaurant", "website designer restaurants" (these are SERVICE PROVIDERS)
  
- "crm for startups" → search: "founder startups linkedin", "coo startup linkedin"
  WRONG: "crm consultant startups", "crm implementation" (these are not buyers)
  
- "marketing for gyms" → search: "gym owner linkedin", "fitness center manager linkedin"
  WRONG: "marketing specialist gym", "digital marketer fitness" (these are service providers)

Return ONLY valid JSON with this structure:
{
  "roles": ["role1", "role2", ...],  // DECISION MAKERS, not service providers
  "industries": ["industry1", "industry2", ...],
  "keywords": ["buyer keyword1", "buyer keyword2", ...],  // BUYER-focused keywords
  "search_queries": ["site:linkedin.com/in \"query1\"", ...]  // Queries for BUYERS
}

Rules:
- roles: job titles of DECISION MAKERS/BUYERS (CEO, Founder, COO, Operations Manager, etc.)
- industries: sectors where buyers work
- keywords: MUST be buyer-focused (e.g., "restaurant owner", "gym owner", "dental practice owner")
- search_queries: MUST find buyers, NOT service providers
- DO NOT generate queries for: developers, designers, consultants, freelancers, agencies
- search_queries format: site:linkedin.com/in "search terms"
- Maximum 6-8 items per list"""

    service_context = f"Product/Service being sold: {service}"
    target_context = f"Buyer industry: {target}" if target else "Buyer industry: (any)"
    
    icp_context = ""
    if has_icp:
        if use_new_schema:
            icp_context = f"""
BUYER-INTENT ICP Data (use this):
- Offer: {icp.get('offer', '')}
- Service Category: {icp.get('service_category', '')}
- Buyer Industries: {', '.join(icp.get('buyer_industries', []))}
- Buyer Roles (BUYERS NOT PROVIDERS): {', '.join(icp.get('buyer_roles', [])[:5])}
- Excluded Roles (DO NOT search for): {', '.join(icp.get('excluded_roles', []))}
- Search Hints: {', '.join(icp.get('search_hints', []))}

Generate search queries that find these BUYERS, not service providers."""
        else:
            icp_context = f"""
Legacy ICP Data:
- Offer: {icp.get('offer', '')}
- Industries: {', '.join(icp.get('industries', []))}
- Target Roles: {', '.join(icp.get('target_roles', []))}

Convert these to BUYER roles (e.g., if target_roles has 'Web Developer', convert to 'Business Owner' or 'Manager')."""

    user_text = f"""{service_context}
{target_context}
{icp_context}

Generate BUYER-FOCUSED search queries. Remember: find who BUYS, not who provides the service."""

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
        _log("Sending request to OpenAI for buyer-intent expansion")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
        
        if response.status_code == 401:
            _log("OpenAI API key is invalid, using deterministic fallback")
            return _get_deterministic_expansion(service, target, icp)
        
        if response.status_code == 429:
            _log("OpenAI API quota exceeded, using deterministic fallback")
            return _get_deterministic_expansion(service, target, icp)
        
        if response.status_code >= 500:
            _log(f"OpenAI API server error: {response.status_code}, using deterministic fallback")
            return _get_deterministic_expansion(service, target, icp)
        
        response.raise_for_status()
        
        data = response.json()
        
        try:
            output_text = data["output"][0]["content"][0]["text"].strip()
        except (KeyError, IndexError):
            output_text = data.get("output_text", "").strip()
        
        if not output_text:
            _log("Empty response from OpenAI, using deterministic fallback")
            return _get_deterministic_expansion(service, target, icp)
        
        _log(f"Raw AI response: {output_text[:200]}...")
        
        result = json.loads(output_text)
        
        result["roles"] = _dedupe_and_cap(result.get("roles", []), 8)
        result["industries"] = _dedupe_and_cap(result.get("industries", []), 6)
        result["keywords"] = _dedupe_and_cap(result.get("keywords", []), 8)
        
        search_queries = []
        for kw in result.get("keywords", [])[:8]:
            clean_kw = kw.replace('"', '').replace('site:linkedin.com/in', '').strip()
            if not clean_kw.startswith('site:'):
                search_queries.append(f'site:linkedin.com/in "{clean_kw}"')
        
        result["search_queries"] = search_queries
        
        excluded_roles = icp.get("excluded_roles", []) if icp else []
        result["excluded_roles"] = excluded_roles
        
        _log(f"AI buyer-intent expansion: {len(result.get('roles', []))} buyer roles, {len(search_queries)} queries")
        
        return result
        
    except requests.Timeout:
        _log("OpenAI request timed out, using deterministic fallback")
        return _get_deterministic_expansion(service, target, icp)
    except requests.ConnectionError as e:
        _log(f"OpenAI connection error: {e}, using deterministic fallback")
        return _get_deterministic_expansion(service, target, icp)
    except json.JSONDecodeError as e:
        _log(f"Failed to parse AI response as JSON: {e}, using deterministic fallback")
        return _get_deterministic_expansion(service, target, icp)
    except Exception as e:
        _log(f"Unexpected error during AI expansion: {e}, using deterministic fallback")
        return _get_deterministic_expansion(service, target, icp)