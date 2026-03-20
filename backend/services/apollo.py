import os
import requests
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"
MOCK_LEADS_ON_403 = [
    {"name": "John Doe", "title": "HR Manager", "company": "TechCorp"},
    {"name": "Sarah Lee", "title": "HR Lead", "company": "StartupX"},
]


def _log(message: str) -> None:
    print(f"[apollo] {message}")


def _map_person_titles(query: str) -> list[str]:
    normalized_query = query.strip().lower()

    if "student" in normalized_query:
        return ["Intern"]

    if "hr manager" in normalized_query or "hr managers" in normalized_query:
        return ["HR Manager"]

    return ["HR Manager"]


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


def _format_mock_lead(lead: dict) -> dict:
    name = (lead.get("name") or "Unknown").strip()
    name_parts = name.split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Unknown"
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    return {
        "first_name": first_name,
        "last_name": last_name,
        "name": name,
        "title": (lead.get("title") or "Professional").strip(),
        "company": (lead.get("company") or "Unknown Company").strip(),
        "email": (lead.get("email") or "").strip(),
        "linkedin_url": (lead.get("linkedin_url") or "").strip(),
    }


def _format_lead(index: int, lead: dict) -> str:
    full_name = " ".join(
        part for part in [lead["first_name"], lead["last_name"]] if part
    ) or "Unknown"

    return f"{index}. {full_name} — {lead['title']} @ {lead['company']}"

def format_leads_message(leads: list[dict]) -> str:
    formatted_leads = [_format_lead(i, lead) for i, lead in enumerate(leads, 1)]
    return (
        "Found these leads:\n\n"
        + "\n".join(formatted_leads)
        + "\n\nReply with the number to select a lead."
    )


def search_leads(query: str) -> dict:
    """Search Apollo and return structured lead results."""
    _log(f"search_leads called: query={query}")
    if not APOLLO_API_KEY:
        _log("search_leads error: missing APOLLO_API_KEY")
        return {
            "ok": False,
            "source": "apollo",
            "leads": [],
            "error": "missing_api_key",
        }

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": APOLLO_API_KEY,
    }

    payload = {
        "page": 1,
        "per_page": 5,
        "person_titles": _map_person_titles(query),
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

        if response.status_code == 403:
            mock_leads = [_format_mock_lead(lead) for lead in MOCK_LEADS_ON_403]
            _log(f"search_leads fallback triggered for 403: {mock_leads}")
            return {
                "ok": True,
                "source": "mock",
                "leads": mock_leads,
                "error": None,
            }

        response.raise_for_status()

        if data is None:
            _log(f"search_leads error: non-JSON response body: {response.text}")
            return {
                "ok": False,
                "source": "apollo",
                "leads": [],
                "error": "non_json_response",
            }

        people = data.get("people", [])
        
        if not people:
            _log(f"search_leads empty response: {data}")
            return {
                "ok": False,
                "source": "apollo",
                "leads": [],
                "error": "empty_response",
            }

        parsed_leads = [_parse_person(person) for person in people[:5]]
        return {
            "ok": True,
            "source": "apollo",
            "leads": parsed_leads,
            "error": None,
        }
        
    except (requests.exceptions.RequestException, ValueError) as e:
        response_text = None
        if "response" in locals():
            response_text = response.text
        _log(f"search_leads request error: {e}")
        _log(f"search_leads exact response body: {response_text}")
        return {
            "ok": False,
            "source": "apollo",
            "leads": [],
            "error": str(e),
        }
