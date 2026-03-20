import os
import requests
from dotenv import load_dotenv
from services.supabase import store_leads

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"
FALLBACK_MESSAGE = "Couldn't fetch leads right now. Try again."


def _log(message: str) -> None:
    print(f"[apollo] {message}")


def _parse_person(person: dict) -> dict:
    organization = person.get("organization") or {}
    first_name = (person.get("first_name") or "").strip()
    last_name = (person.get("last_name") or "").strip()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "name": " ".join(part for part in [first_name, last_name] if part) or "Unknown",
        "title": (person.get("title") or "Professional").strip(),
        "company": (organization.get("name") or "Unknown Company").strip(),
        "email": (person.get("email") or "").strip(),
        "linkedin_url": (person.get("linkedin_url") or "").strip(),
    }


def _format_lead(index: int, lead: dict) -> str:
    full_name = " ".join(
        part for part in [lead["first_name"], lead["last_name"]] if part
    ) or "Unknown"

    return f"{index}. {full_name} — {lead['title']} at {lead['company']}"

def search_leads(query: str, user_id: str) -> str:
    """Search Apollo for leads and return a conversational top-five list."""
    _log(f"search_leads called: query={query}, user_id={user_id}")
    if not APOLLO_API_KEY:
        _log("search_leads error: missing APOLLO_API_KEY")
        return FALLBACK_MESSAGE

    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "api_key": APOLLO_API_KEY,
        "q_keywords": query,
        "page": 1,
        "per_page": 5
    }
    
    try:
        _log(f"search_leads request payload: {payload}")
        response = requests.post(
            APOLLO_SEARCH_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
        try:
            data = response.json()
        except ValueError:
            data = None

        _log(f"search_leads response status: {response.status_code}")
        _log(f"search_leads response json: {data}")

        response.raise_for_status()

        if data is None:
            _log(f"search_leads error: non-JSON response body: {response.text}")
            return FALLBACK_MESSAGE

        people = data.get("people", [])
        
        if not people:
            _log(f"search_leads empty response: {data}")
            return FALLBACK_MESSAGE

        parsed_leads = [_parse_person(person) for person in people[:5]]
        store_leads(user_id, parsed_leads)
        formatted_leads = [_format_lead(i, lead) for i, lead in enumerate(parsed_leads, 1)]
            
        return "Found these leads:\n\n" + "\n".join(formatted_leads) + "\n\nApprove one?"
        
    except (requests.exceptions.RequestException, ValueError) as e:
        response_text = None
        if "response" in locals():
            response_text = response.text
        _log(f"search_leads request error: {e}")
        _log(f"search_leads exact response body: {response_text}")
        return FALLBACK_MESSAGE
