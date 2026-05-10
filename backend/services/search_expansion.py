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


def _get_deterministic_expansion(service: str, target: Optional[str]) -> dict:
    """Generate deterministic expansion when AI is unavailable"""
    _log("Using deterministic fallback expansion")
    
    service_clean = service.strip() if service else ""
    target_clean = target.strip() if target else ""
    
    roles = [service_clean] if service_clean else []
    industries = [service_clean] if service_clean else []
    keywords = []
    
    if service_clean and target_clean:
        keywords.append(f"{service_clean} {target_clean}")
        keywords.append(f"{service_clean} {target_clean} linkedin")
    elif service_clean:
        keywords.append(service_clean)
        keywords.append(f"{service_clean} linkedin")
    
    search_queries = []
    for kw in keywords[:5]:
        search_queries.append(f'site:linkedin.com/in "{kw}"')
    
    return {
        "roles": roles,
        "industries": industries,
        "keywords": keywords,
        "search_queries": search_queries,
    }


def expand_search_intent(
    service: str,
    target: Optional[str] = None
) -> dict:
    """
    Expand search intent using AI semantic understanding.
    
    Args:
        service: What the user sells (e.g., "CRM", "AI automation")
        target: Optional target audience (e.g., "startups", "law firms")
    
    Returns:
        dict with roles, industries, keywords, and search_queries
    """
    if not service:
        _log("No service provided, using empty expansion")
        return _get_deterministic_expansion("", None)
    
    if not OPENAI_API_KEY:
        _log("OPENAI_API_KEY not configured, using deterministic fallback")
        return _get_deterministic_expansion(service, target)
    
    _log(f"Expanding intent: service='{service}', target='{target}'")
    
    system_text = """You are a B2B sales lead search strategist. Your job is to expand vague search intent into specific search queries.

Given a product/service and optional target audience, generate:
1. RELATED ROLES: Job titles that would be buyers or champions
2. ADJACENT INDUSTRIES: Related industries that might use this
3. KEYWORDS: Search terms combining product + role/target
4. LINKEDIN SEARCH QUERIES: Optimized queries for LinkedIn profile search

Return ONLY valid JSON with this structure:
{
  "roles": ["role1", "role2", ...],
  "industries": ["industry1", "industry2", ...],
  "keywords": ["keyword1", "keyword2", ...],
  "search_queries": ["site:linkedin.com/in \"query1\"", ...]
}

Rules:
- roles should be actual job titles (CRM Manager, VP Sales, etc.)
- industries should be sectors (SaaS, Healthcare, Finance, etc.)
- keywords combine service + role/target naturally
- search_queries must be in format: site:linkedin.com/in "search terms"
- DO NOT invent fake names or companies
- Be specific but not overly narrow
- Maximum 5-8 items per category"""

    service_context = f"Product/Service: {service}"
    target_context = f"Target Audience: {target}" if target else "Target Audience: (any)"
    
    user_text = f"""{service_context}
{target_context}

Generate the expanded search intent."""

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
        _log("Sending request to OpenAI for semantic expansion")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
        
        if response.status_code == 401:
            _log("OpenAI API key is invalid")
            return _get_deterministic_expansion(service, target)
        
        if response.status_code == 429:
            _log("OpenAI API quota exceeded")
            return _get_deterministic_expansion(service, target)
        
        if response.status_code >= 500:
            _log(f"OpenAI API server error: {response.status_code}")
            return _get_deterministic_expansion(service, target)
        
        response.raise_for_status()
        
        data = response.json()
        
        try:
            output_text = data["output"][0]["content"][0]["text"].strip()
        except (KeyError, IndexError):
            output_text = data.get("output_text", "").strip()
        
        if not output_text:
            _log("Empty response from OpenAI")
            return _get_deterministic_expansion(service, target)
        
        _log(f"Raw AI response: {output_text[:200]}...")
        
        result = json.loads(output_text)
        
        result["roles"] = result.get("roles", [])[:8]
        result["industries"] = result.get("industries", [])[:6]
        result["keywords"] = result.get("keywords", [])[:8]
        
        search_queries = []
        for kw in result.get("keywords", [])[:8]:
            search_queries.append(f'site:linkedin.com/in "{kw}"')
        
        result["search_queries"] = search_queries
        
        _log(f"AI expansion success: {len(result.get('roles', []))} roles, {len(result.get('search_queries', []))} queries")
        
        return result
        
    except requests.Timeout:
        _log("OpenAI request timed out, using deterministic fallback")
        return _get_deterministic_expansion(service, target)
    except requests.ConnectionError as e:
        _log(f"OpenAI connection error: {e}, using deterministic fallback")
        return _get_deterministic_expansion(service, target)
    except json.JSONDecodeError as e:
        _log(f"Failed to parse AI response as JSON: {e}")
        return _get_deterministic_expansion(service, target)
    except Exception as e:
        _log(f"Unexpected error during AI expansion: {e}")
        return _get_deterministic_expansion(service, target)