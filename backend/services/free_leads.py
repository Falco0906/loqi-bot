import os
import re


class SerpAPIError(Exception):
    """Raised when SerpAPI fails and should not return fake data"""
    pass


def build_search_query(query: str) -> str:
    """Build a proper LinkedIn people search query"""
    return f'site:linkedin.com/in "{query}"'


def clean_text(text: str) -> str:
    return text.replace("...", "").replace("|", "").strip()


def extract_company(title: str, snippet: str) -> str:
    title = title.replace("| LinkedIn", "").strip()
    
    parts = [part.strip() for part in title.split(" - ") if part.strip()]
    
    if len(parts) >= 3:
        return clean_text(parts[2])

    match = re.search(r"at\s+([A-Za-z0-9&.\- ]+?)(?:\s*[-|]|$)", title, re.IGNORECASE)
    if match:
        return clean_text(match.group(1).strip())

    match = re.search(r",\s*([A-Z][A-Za-z0-9&\- ]+?)(?:\s*$|\s*[-|])", title)
    if match:
        return clean_text(match.group(1).strip())

    if snippet:
        match = re.search(r"at\s+([A-Za-z0-9&.\- ]+?)(?:\s*[-|]|$)", snippet, re.IGNORECASE)
        if match:
            return clean_text(match.group(1).strip())

    return ""


def search_free_leads(query: str) -> list[dict]:
    print("[free_leads] query:", query)

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise SerpAPIError("SERPAPI_API_KEY not configured. Lead search unavailable.")

    try:
        from serpapi import Client
    except ImportError as e:
        raise SerpAPIError(f"SerpAPI package not installed: {e}. Lead search unavailable.")

    built_query = build_search_query(query)
    print("[free_leads] built_query:", built_query)

    try:
        client = Client(api_key=api_key)
        results = client.search(q=built_query, engine="google", num=15)
        
        organic_results = results.get("organic_results", [])
        
        leads = []
        seen_names = set()

        for result in organic_results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            link = result.get("link", "")

            if "linkedin.com/in/" not in link:
                continue

            title = title.replace("| LinkedIn", "").strip()
            
            company = ""
            
            if " - " in title:
                parts = title.split(" - ", 1)
                name = parts[0].strip()
                role_with_company = parts[1].strip() if len(parts) > 1 else ""
                
                if " at " in role_with_company.lower():
                    role_parts = role_with_company.rsplit(" at ", 1)
                    role = role_parts[0].strip()
                    company = role_parts[1].strip()
                elif ", " in role_with_company:
                    comma_pos = role_with_company.rfind(", ")
                    if comma_pos > 0:
                        potential_company = role_with_company[comma_pos+2:].strip()
                        if potential_company and len(potential_company) < 40:
                            company = potential_company
                            role = role_with_company[:comma_pos].strip()
                        else:
                            role = role_with_company
                    else:
                        role = role_with_company
                else:
                    role = role_with_company
                    company = extract_company(title, snippet)
            else:
                name = title
                role = ""
                company = extract_company(title, snippet)
            
            if not name:
                continue
                
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
                
            role = clean_text(role)
            if not company:
                company = extract_company(title, snippet)

            if not name or not role:
                continue

            leads.append(
                {
                    "name": name,
                    "title": role,
                    "company": company,
                    "email": "",
                    "linkedin_url": link,
                }
            )

            if len(leads) >= 5:
                break

        print("[free_leads] leads:", leads)

        if not leads:
            raise SerpAPIError("No leads found for this query. Try a different target.")

        return leads
    except Exception as e:
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise SerpAPIError("SerpAPI API key is invalid")
        if "quota" in error_msg.lower() or "limit" in error_msg.lower():
            raise SerpAPIError("SerpAPI quota exceeded")
        raise SerpAPIError(f"SerpAPI request failed: {error_msg}")